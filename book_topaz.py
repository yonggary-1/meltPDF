"""
AZW1(Topaz) 읽기 - 킨들의 옛 Topaz 책(.azw1, .tpz, 일부 .azw)에서 삽화 이미지와 서지 정보만 꺼낸다.

Topaz는 스캔한 책을 글자 모양(glyph)과 위치로 바꿔 담은 형식이라 쪽 자체는 이미지가 아니다. 쪽을 다시 그리는 일은
하지 않고("파일 안의 원래 이미지를 그대로 꺼낸다"는 원칙), 파일에 이미지로 들어 있는 것(삽화, 표지 등)만 꺼낸다.

파일 구조(공개 문서는 없고, calibre의 metadata/topaz.py와 DeDRM의 topazextract.py가 쓰는 구조를 따른다):
- 'TPZ' + 버전 글자, 머리 레코드 개수(가변 길이 정수), 머리 레코드들, 0x64('d'), 그 뒤가 본문(base).
- 머리 레코드: 0x63('c'), 이름(길이+바이트), 항목 수, 항목마다 (본문 안 위치, 원래 길이, 압축된 길이).
- 본문 레코드: 이름(길이+바이트), 번호(음수면 암호화됨), 데이터(압축된 길이가 0보다 크면 zlib).
- 'img'는 이미지, 'color'는 같은 번호 이미지의 컬러판(있으면 컬러판을 쓴다), 'metadata'는 서지 정보(Title, Authors 등).
- 'dkey' 레코드가 있거나 암호화된 레코드가 있으면 DRM이 걸린 책이므로 열지 않는다(우회하지 않는다).
- 가변 길이 정수: 7비트씩 큰 자리부터, 앞 비트가 1이면 이어짐. 첫 바이트가 0xFF면 음수 표시.

순서: 이미지 번호 순(파일에 저장된 순서)이다. 쪽 레코드에서 이미지가 쓰이는 자리를 찾지 않으므로 책 순서와 다를 수 있다.
"""
from __future__ import annotations

import os
import zlib
from typing import BinaryIO, Dict, List, Optional, Tuple

import book_meta
import temp_store
from archive_zip import MAX_ENTRY_BYTES, MAX_TOTAL_BYTES
from book_common import BookError, ExtractedImage, ExtractResult, ProgressFn, noop_progress

_MAGIC = ((b"\xff\xd8", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"), (b"GIF87a", ".gif"), (b"GIF89a", ".gif"), (b"BM", ".bmp"))
MAX_HEADER_RECORDS = 1000
MAX_ENTRIES = 1_000_000
MAX_META_BYTES = 1024 * 1024

Entry = Tuple[int, int, int]          # (본문 안 위치, 원래 길이, 압축된 길이)


class _Encrypted(Exception):
    pass


def is_topaz_file(head: bytes) -> bool:
    return len(head) >= 4 and head[:3] == b"TPZ" and 0x30 <= head[3] <= 0x39


def _image_ext(head: bytes) -> Optional[str]:
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    return None


def _byte(f: BinaryIO) -> int:
    b = f.read(1)
    if not b:
        raise BookError("Topaz 파일이 중간에서 끊겼거나 손상되었습니다.")
    return b[0]


def _vwi(f: BinaryIO) -> int:
    data = _byte(f)
    negative = data == 0xFF
    if negative:
        data = _byte(f)
    if data >= 0x80:
        value = data & 0x7F
        for _ in range(8):
            data = _byte(f)
            value = (value << 7) | (data & 0x7F)
            if data < 0x80:
                break
        else:
            raise BookError("Topaz 파일의 숫자 정보가 손상되었습니다.")
        data = value
    return -data if negative else data


def _string(f: BinaryIO, limit: int = 256) -> bytes:
    n = _vwi(f)
    if not 0 <= n <= limit:
        raise BookError("Topaz 파일의 이름 정보가 손상되었습니다.")
    s = f.read(n)
    if len(s) != n:
        raise BookError("Topaz 파일이 중간에서 끊겼거나 손상되었습니다.")
    return s


def _headers(f: BinaryIO, size: int) -> Tuple[Dict[bytes, List[Entry]], int]:
    f.seek(0)
    if not is_topaz_file(f.read(4)):
        raise BookError("Topaz(azw1) 파일이 아닙니다.")
    count = _vwi(f)
    if not 0 < count <= MAX_HEADER_RECORDS:
        raise BookError("Topaz 파일의 머리 정보가 손상되었습니다.")
    headers: Dict[bytes, List[Entry]] = {}
    for _ in range(count):
        if _byte(f) != 0x63:
            raise BookError("Topaz 파일의 머리 정보가 손상되었습니다.")
        name = _string(f)
        n = _vwi(f)
        if not 0 <= n <= MAX_ENTRIES:
            raise BookError("Topaz 파일의 머리 정보가 손상되었습니다.")
        headers[name] = [(_vwi(f), _vwi(f), _vwi(f)) for _ in range(n)]
    if _byte(f) != 0x64:
        raise BookError("Topaz 파일의 머리 정보가 손상되었습니다.")
    return headers, f.tell()


def _record(f: BinaryIO, base: int, size: int, name: bytes, index: int, entry: Entry) -> bytes:
    offset, ulen, clen = entry
    if offset < 0 or ulen < 0 or clen < 0:
        raise BookError(f"Topaz 파일의 {name.decode('latin-1')} 레코드 위치가 잘못되었습니다.")
    if base + offset >= size:
        raise BookError("파일 끝이 잘려 이 이미지가 없습니다.")
    if ulen > MAX_ENTRY_BYTES or clen > MAX_ENTRY_BYTES:
        raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name.decode('latin-1')} {index}")
    f.seek(base + offset)
    if _string(f) != name:
        raise BookError(f"Topaz 파일의 {name.decode('latin-1')} 레코드가 손상되었습니다.")
    rec_index = _vwi(f)
    if rec_index < 0:
        raise _Encrypted()
    if rec_index != index:
        raise BookError(f"Topaz 파일의 {name.decode('latin-1')} 레코드 번호가 맞지 않습니다.")
    data = f.read(clen if clen > 0 else ulen)
    if clen > 0:
        try:
            d = zlib.decompressobj()
            data = d.decompress(data, ulen + 1 if ulen else MAX_ENTRY_BYTES)
        except zlib.error:
            raise BookError(f"Topaz 파일의 {name.decode('latin-1')} 레코드 압축을 풀지 못했습니다.")
    return data


def _complete(data: bytes, entry: Entry) -> bool:
    """레코드가 머리에 적힌 길이만큼 다 있는가(파일 끝이 잘렸으면 False - 읽힌 부분만 쓰고 손상 표시)."""
    return len(data) >= entry[1]


def _read_meta(f: BinaryIO, base: int, size: int, headers: Dict[bytes, List[Entry]], source: str) -> book_meta.BookMeta:
    m = book_meta.BookMeta(source=source)
    entries = headers.get(b"metadata") or []
    if not entries:
        return m
    offset, ulen, _clen = entries[0]
    if base + offset >= size:
        return m
    values: Dict[str, str] = {}
    try:
        f.seek(base + offset)
        if _string(f) != b"metadata":
            return m
        _flags = _byte(f)
        for _ in range(_byte(f)):
            key = _string(f).decode("utf-8", "replace")
            value = _string(f, MAX_META_BYTES).decode("utf-8", "replace")
            values.setdefault(key.lower(), value)
    except BookError:
        pass                                  # 서지 정보가 깨진 것은 이미지 꺼내기를 막지 않는다
    m.title = values.get("updatedtitle") or values.get("title", "")
    m.author = book_meta.join_unique(book_meta.split_list(values.get("authors", ""), ";"), "; ")
    m.publisher = values.get("publisher", "")
    m.language = values.get("language", "")
    m.subject = book_meta.strip_html(values.get("description", ""))
    return m.clean()


def _open(path: str):
    try:
        f = open(path, "rb")
        size = os.path.getsize(path)
    except OSError as e:
        raise BookError(f"파일을 열 수 없습니다: {e}")
    try:
        headers, base = _headers(f, size)
    except Exception:
        f.close()
        raise
    return f, size, headers, base


def estimate_bytes(path: str) -> int:
    try:
        f, size, headers, base = _open(path)
        with f:
            return sum(u for name in (b"img", b"color") for _o, u, _c in headers.get(name, []))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def extract_topaz(path: str, on_progress: ProgressFn = noop_progress, to_ram: bool = False) -> List[ExtractedImage]:
    f, size, headers, base = _open(path)
    with f:
        if b"dkey" in headers:
            raise BookError("저작권 보호(DRM)가 걸린 책이라 열지 않습니다.")
        results = ExtractResult(meta=_read_meta(f, base, size, headers, os.path.basename(path)))
        imgs = headers.get(b"img") or []
        colors = headers.get(b"color") or []
        if sum(e[1] for e in imgs) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        total = len(imgs)
        if not total:
            results.warnings.append("azw1(Topaz)은 쪽이 이미지가 아니라 글자 모양으로 저장된 형식이라, 꺼낼 수 있는 것은 "
                                    "파일에 이미지로 들어 있는 삽화/표지뿐입니다. 이 책에는 그런 이미지가 없습니다.")
        else:
            results.notes.append("azw1(Topaz)은 쪽이 이미지가 아니라 글자 모양으로 저장된 형식이라, 파일에 이미지로 들어 있는 "
                                 "삽화/표지만 꺼냈습니다. 순서는 파일에 저장된 이미지 번호 순입니다.")
        for i, entry in enumerate(imgs):
            data = None
            try:
                if i < len(colors):                       # 같은 번호의 컬러판이 있으면 그것을 쓴다
                    c = _record(f, base, size, b"color", i, colors[i])
                    if _image_ext(c[:12]):
                        data, complete = c, _complete(c, colors[i])
                if data is None:
                    data = _record(f, base, size, b"img", i, entry)
                    complete = _complete(data, entry)
            except _Encrypted:
                raise BookError("저작권 보호(DRM)가 걸린 책이라 열지 않습니다.")
            except BookError as e:
                results.warnings.append(f"image_{i + 1:05d}: {e} 목록에서 뺐습니다.")
                continue
            ext = _image_ext(data[:12])
            if not ext:
                results.warnings.append(f"image_{i + 1:05d}: 이미지가 아니거나 지원하지 않는 형식이라 뺐습니다.")
                continue
            label = f"image_{i + 1:05d}{ext}"
            if to_ram:
                results.append(ExtractedImage(label=label, data=data, damaged=not complete))
            else:
                out_path = temp_store.new_path(ext)
                try:
                    with open(out_path, "wb") as out:
                        out.write(data)
                except OSError as e:
                    raise BookError(f"'{label}'을(를) 저장하지 못했습니다: {e}")
                results.append(ExtractedImage(label=label, path=out_path, damaged=not complete))
            on_progress(i + 1, total)
        return results
