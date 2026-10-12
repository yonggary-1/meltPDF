"""
tar / cbt 읽기 - tar 묶음 안의 이미지를 이름 순(zip/rar와 같은 자연 정렬)으로 꺼낸다. 파이썬 기본 tarfile만 쓴다.

- gzip/bzip2/xz로 압축한 tar(.tar.gz 등)도 같은 방식으로 열린다(tarfile이 알아서 푼다).
- 압축된 tar는 뒤로 되감기가 매우 느리므로, 파일에 저장된 순서대로 한 번만 읽은 뒤 이름 순으로 정렬한다.
- 보통 파일만 읽는다(링크, 장치 파일 등은 무시). 디스크에는 이름이 아니라 temp_store의 임시 이름으로 쓰므로 경로 조작 걱정이 없다.
- 이름: PAX(UTF-8) 이름은 그대로, 옛 tar의 바이트 이름은 name_codec으로 문자 코드를 추정해 복원한다(zip과 같은 규칙).
- 끝이 잘린 tar: 읽힌 데까지 넣고, 중간에서 끊긴 이미지는 손상 표시, 안내를 띄운다.
"""
from __future__ import annotations

import io
import os
import tarfile
from zlib import error as zlib_error
from pathlib import PurePosixPath
from typing import List, Tuple

import name_codec
import temp_store
from archive_zip import MAX_ENTRY_BYTES, MAX_TOTAL_BYTES
from book_common import BookError, ExtractedImage, ExtractResult, ProgressFn, is_image_name, noop_progress
from natural_sort import path_key

_CHUNK = 1024 * 1024
COMPRESSED_MAGIC = (b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")


def looks_like_tar(head: bytes) -> bool:
    """파일 앞 512바이트가 ustar/GNU tar 머리인가(압축하지 않은 tar)."""
    return len(head) >= 262 and head[257:262] == b"ustar"


def is_compressed_tar(path: str, head: bytes) -> bool:
    """gzip/bzip2/xz로 압축된 tar인가(풀어서 첫 머리를 확인한다)."""
    if not head.startswith(COMPRESSED_MAGIC):
        return False
    try:
        return tarfile.is_tarfile(path)
    except Exception:
        return False


def _open(path: str) -> tarfile.TarFile:
    try:
        return tarfile.open(path, "r:*", encoding="utf-8", errors="surrogateescape")
    except (tarfile.TarError, EOFError, OSError) as e:
        raise BookError(f"tar 파일이 손상되었거나 tar 형식이 아닙니다: {e}")


def _members(tf: tarfile.TarFile) -> Tuple[List[tarfile.TarInfo], bool]:
    """보통 파일 항목들(저장된 순서)과, 목록을 끝까지 읽지 못했는지(잘린 파일)."""
    out: List[tarfile.TarInfo] = []
    cut = False
    while True:
        try:
            m = tf.next()
        except (tarfile.TarError, EOFError, OSError):
            cut = True
            break
        if m is None:
            break
        if m.isfile():
            out.append(m)
    return out, cut


def _names(members: List[tarfile.TarInfo]) -> List[str]:
    """깨진(UTF-8이 아닌) 이름은 바이트로 되돌려 문자 코드를 추정해 다시 읽는다."""
    raws = [m.name.encode("utf-8", "surrogateescape") for m in members]
    bad = [r for r, m in zip(raws, members) if any(0xDC80 <= ord(c) <= 0xDCFF for c in m.name)]
    if not bad:
        return [m.name for m in members]
    enc = name_codec.guess_encoding(bad)
    out = []
    for r, m in zip(raws, members):
        if any(0xDC80 <= ord(c) <= 0xDCFF for c in m.name):
            out.append(r.decode(enc, "replace"))
        else:
            out.append(m.name)
    return out


def estimate_bytes(path: str) -> int:
    try:
        with _open(path) as tf:
            members, _cut = _members(tf)
            return sum(m.size for m, n in zip(members, _names(members)) if is_image_name(n))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def _copy(tf: tarfile.TarFile, m: tarfile.TarInfo, dst, name: str) -> int:
    """항목 m의 내용을 dst로 옮기고 옮긴 바이트 수를 돌려준다. 파일이 중간에서 끊겼으면 거기까지만 옮긴다.
    tarfile.extractfile은 끝이 모자라면 앞부분까지 버리고 오류를 내므로, 보통 파일은 묶음 안의 위치에서 직접 읽는다."""
    if m.issparse():                                   # 드문 '성긴 파일'은 tarfile에 맡긴다
        src = tf.extractfile(m)
        read = src.read
    else:
        tf.fileobj.seek(m.offset_data)
        left = m.size

        def read(n):
            nonlocal left
            chunk = tf.fileobj.read(min(n, left)) if left > 0 else b""
            left -= len(chunk)
            return chunk
    written = 0
    while True:
        try:
            chunk = read(_CHUNK)
        except (tarfile.TarError, EOFError, OSError, zlib_error):
            break
        if not chunk:
            break
        written += len(chunk)
        if written > MAX_ENTRY_BYTES:
            raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name}")
        dst.write(chunk)
    return written


def extract_tar(path: str, on_progress: ProgressFn = noop_progress, to_ram: bool = False) -> List[ExtractedImage]:
    with _open(path) as tf:
        members, cut = _members(tf)
        picks = [(m, n) for m, n in zip(members, _names(members)) if is_image_name(n)]
        if sum(m.size for m, _ in picks) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        results = ExtractResult()
        if cut:
            results.notes.append("tar 파일의 끝이 잘려 있어 읽을 수 있는 데까지만 가져왔습니다. 뒤쪽 파일이 빠져 있을 수 있습니다.")
        got = []
        total = len(picks)
        for done, (m, name) in enumerate(picks, start=1):          # 저장된 순서로 읽는다(압축된 tar의 되감기를 피함)
            if m.size > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name}")
            if to_ram:
                buf = io.BytesIO()
                n = _copy(tf, m, buf, name)
                item = ExtractedImage(label=name, data=buf.getvalue(), damaged=n < m.size)
            else:
                out_path = temp_store.new_path(PurePosixPath(name).suffix.lower())
                try:
                    with open(out_path, "wb") as dst:
                        n = _copy(tf, m, dst, name)
                except OSError as e:
                    raise BookError(f"'{name}'을(를) 저장하지 못했습니다: {e}")
                item = ExtractedImage(label=name, path=out_path, damaged=n < m.size)
            if n == 0 and m.size > 0:
                results.warnings.append(f"{name}: 손상되어 읽지 못했습니다. 목록에서 뺐습니다.")
                continue
            got.append(item)
            on_progress(done, total)
        got.sort(key=lambda it: path_key(it.label))                 # 이름 순(자연 정렬)
        results.extend(got)
        return results
