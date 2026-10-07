"""
ZIP / CBZ 읽기 - 압축 파일 안의 이미지를 "파일에 저장된 순서" 그대로 꺼낸다(이름 순이 아님).

- 저장 순서 = 파일 안에서 각 항목이 실제로 기록된 위치(header_offset) 순서. 중앙 디렉터리 목록
  순서는 도구에 따라 다를 수 있어서 쓰지 않는다.
- 이미지는 재인코딩 없이 원본 바이트 그대로 꺼낸다(메모리 또는 디스크 임시 폴더 - 호출하는 쪽이 고른다).
- 윈도우 한글 zip(이름이 cp949인데 UTF-8 표시가 없는 것)의 깨진 이름을 복원한다. 이름은 목록 표시용이고
  순서와는 무관하다.
- 암호 걸린 zip, 비정상적으로 큰 항목(압축 폭탄)은 사유를 알려 주고 거절한다.
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import PurePosixPath
from typing import List

from book_common import BookError, ExtractedImage, ProgressFn, is_image_name, noop_progress
import temp_store

MAX_ENTRY_BYTES = 1024 * 1024 * 1024        # 항목 하나 최대 1GB
MAX_TOTAL_BYTES = 16 * 1024 * 1024 * 1024   # 이미지 전체 합계 최대 16GB
_CHUNK = 1024 * 1024
_NAME_ENCODINGS = ("utf-8", "cp949", "cp932", "gbk")


def _entry_name(info: zipfile.ZipInfo) -> str:
    """항목 이름을 사람이 읽을 수 있게 복원한다. 파이썬은 UTF-8 표시(0x800)가 없으면 cp437로
    읽으므로, 그 경우 원래 바이트로 되돌려서 UTF-8 -> cp949 -> cp932 -> gbk 순으로 해석해 본다."""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            raw = name.encode("cp437")
        except UnicodeEncodeError:
            raw = None
        if raw is not None:
            for enc in _NAME_ENCODINGS:
                try:
                    name = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
    return name.replace("\\", "/")


def _copy_limited(src, dst, name: str) -> None:
    written = 0
    while True:
        chunk = src.read(_CHUNK)
        if not chunk:
            return
        written += len(chunk)
        if written > MAX_ENTRY_BYTES:       # 헤더의 크기를 속이는 경우 대비
            raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name}")
        dst.write(chunk)


def _read_limited(src, name: str) -> bytes:
    buf = io.BytesIO()
    _copy_limited(src, buf, name)
    return buf.getvalue()


def estimate_bytes(path: str) -> int:
    """꺼낼 이미지들의 압축 해제 후 크기 합계(목차만 읽으므로 빠르다). 알 수 없으면 파일 크기."""
    try:
        with zipfile.ZipFile(path) as zf:
            return sum(i.file_size for i in zf.infolist()
                       if not i.is_dir() and is_image_name(_entry_name(i)))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def extract_zip(path: str, on_progress: ProgressFn = noop_progress,
                to_ram: bool = False) -> List[ExtractedImage]:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise BookError("zip 파일이 손상되었거나 zip 형식이 아닙니다.")
    except OSError as e:
        raise BookError(f"파일을 열 수 없습니다: {e}")

    with zf:
        candidates = []
        for info in zf.infolist():
            name = _entry_name(info)
            if not info.is_dir() and is_image_name(name):
                candidates.append((info, name))
        candidates.sort(key=lambda pair: pair[0].header_offset)   # 파일에 저장된 순서

        if any(info.flag_bits & 0x1 for info, _ in candidates):
            raise BookError("암호가 걸린 zip은 아직 지원하지 않습니다.")
        if sum(info.file_size for info, _ in candidates) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")

        results: List[ExtractedImage] = []
        total = len(candidates)
        for done, (info, name) in enumerate(candidates, start=1):
            if info.file_size > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name}")
            try:
                with zf.open(info) as src:
                    if to_ram:
                        data = _read_limited(src, name)
                        results.append(ExtractedImage(label=name, data=data))
                    else:
                        out_path = temp_store.new_path(PurePosixPath(name).suffix.lower())
                        with open(out_path, "wb") as dst:
                            _copy_limited(src, dst, name)
                        results.append(ExtractedImage(label=name, path=out_path))
            except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as e:
                raise BookError(f"'{name}'을(를) 읽지 못했습니다: {e}")
            on_progress(done, total)
        return results
