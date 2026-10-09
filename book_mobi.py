"""
MOBI / AZW / AZW3 읽기 - 킨들 계열 전자책 안의 이미지를 "책을 읽는 순서"로 꺼낸다.

구조(PalmDB): 파일은 레코드 여러 개로 나뉜다. 0번 레코드가 머리(압축 방식, 암호화 표시, 이미지 레코드가 시작되는 번호 등)이고,
뒤에 본문 글 레코드(압축됨), 그 뒤에 이미지 레코드(JPEG/PNG/GIF/BMP 바이트 그대로)가 이어진다.
- 이미지 레코드의 저장 순서는 읽는 순서와 다를 수 있다(변환 도구가 이름순으로 번호를 매기는 경우가 있다). 그래서 본문 글을 풀어서
  이미지를 부르는 자리를 읽는 순서대로 찾는다: MOBI는 `<img recindex="00003">`, AZW3(KF8)는 `kindle:embed:0003`(32진수). 번호는 첫 이미지
  레코드부터 센다(1부터).
- 본문이 PalmDOC 압축(가장 흔함)이거나 압축 안 됨이면 위 방식으로 순서를 정한다. 허프만(HUFF/CDIC) 압축은 풀지 않고, 이미지 레코드가
  저장된 순서대로 가져온다(순서가 다를 수 있다고 알린다).
- 표지(EXTH 201)는 맨 앞에 두고, 표지 썸네일(EXTH 202)은 뺀다. 본문에서 부르지 않은 이미지는 부른 이미지가 하나도 없을 때만 넣는다.
- MOBI와 AZW3가 함께 들어 있는 파일(combo)은 MOBI 쪽만 읽는다(두 쪽이 같은 이미지 레코드를 쓴다).
- DRM(암호화 표시가 있음)은 열지 않는다(우회하지 않는다). Topaz(.azw1), KFX(.azw8/.kfx) 등 다른 킨들 형식은 지원하지 않는다.
- 이미지는 재인코딩 없이 레코드 바이트 그대로 꺼낸다.
"""
from __future__ import annotations

import os
import re
import struct
from typing import BinaryIO, List, Optional

import temp_store
from archive_zip import MAX_ENTRY_BYTES, MAX_TOTAL_BYTES
from book_common import BookError, ExtractedImage, ExtractResult, ProgressFn, noop_progress

_MAGIC = ((b"\xff\xd8", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"), (b"GIF87a", ".gif"), (b"GIF89a", ".gif"), (b"BM", ".bmp"))
_RECINDEX = re.compile(rb'<img[^>]*?\brecindex\s*=\s*["\']?(\d+)', re.IGNORECASE)
_EMBED = re.compile(rb"kindle:embed:([0-9A-Va-v]{1,4})")
MAX_RECORDS = 65535


def is_mobi_file(head: bytes) -> bool:
    """파일 앞부분(최소 68바이트)이 MOBI/AZW/AZW3(PalmDB 'BOOKMOBI')인가."""
    return len(head) >= 68 and head[60:68] == b"BOOKMOBI"


def _image_ext(head: bytes) -> Optional[str]:
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    return None


class _Pdb:
    """PalmDB 파일: 레코드를 번호로 읽는다(파일 전체를 메모리에 올리지 않는다)."""

    def __init__(self, f: BinaryIO, size: int):
        self.f = f
        head = f.read(78)
        if len(head) < 78:
            raise BookError("MOBI 파일이 너무 짧거나 손상되었습니다.")
        self.count = struct.unpack(">H", head[76:78])[0]
        table = f.read(8 * self.count)
        if self.count < 2 or len(table) < 8 * self.count:
            raise BookError("MOBI 파일의 레코드 목록이 손상되었습니다.")
        self.offsets = [struct.unpack(">I", table[8 * i:8 * i + 4])[0] for i in range(self.count)] + [size]
        for a, b in zip(self.offsets, self.offsets[1:]):
            if b < a or a > size:
                raise BookError("MOBI 파일의 레코드 목록이 손상되었습니다.")

    def size(self, i: int) -> int:
        return self.offsets[i + 1] - self.offsets[i]

    def read(self, i: int, n: int = -1) -> bytes:
        self.f.seek(self.offsets[i])
        length = self.size(i) if n < 0 else min(n, self.size(i))
        return self.f.read(length)


class _Header:
    def __init__(self, r0: bytes):
        if len(r0) < 132 or r0[16:20] != b"MOBI":
            raise BookError("MOBI 머리를 읽지 못했습니다. 지원하지 않는 킨들 형식일 수 있습니다.")
        self.compression, _u, self.text_length, self.text_records, _rs, self.encryption = struct.unpack(">HHIHHH", r0[:14])
        self.header_len = struct.unpack(">I", r0[20:24])[0]
        self.version = struct.unpack(">I", r0[36:40])[0]
        self.first_image = struct.unpack(">I", r0[108:112])[0]
        self.extra_flags = 0
        if self.header_len >= 0xE4 and len(r0) >= 0xF4:
            self.extra_flags = struct.unpack(">H", r0[0xF2:0xF4])[0]
        self.exth = {}
        flags = struct.unpack(">I", r0[128:132])[0]
        pos = 16 + self.header_len
        if flags & 0x40 and r0[pos:pos + 4] == b"EXTH":
            try:
                count = struct.unpack(">I", r0[pos + 8:pos + 12])[0]
                p = pos + 12
                for _ in range(min(count, 1000)):
                    rtype, rlen = struct.unpack(">II", r0[p:p + 8])
                    if rlen < 8:
                        break
                    self.exth.setdefault(rtype, r0[p + 8:p + rlen])
                    p += rlen
            except struct.error:
                pass

    def exth_int(self, rtype: int) -> Optional[int]:
        v = self.exth.get(rtype)
        return int.from_bytes(v, "big") if v else None


def _palmdoc_decompress(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        i += 1
        if 1 <= c <= 8:
            out += data[i:i + c]
            i += c
        elif c < 0x80:
            out.append(c)
        elif c >= 0xC0:
            out.append(0x20)
            out.append(c ^ 0x80)
        else:
            if i >= n:
                break
            c = (c << 8) | data[i]
            i += 1
            dist, length = (c >> 3) & 0x7FF, (c & 7) + 3
            if dist == 0 or dist > len(out):
                break                                   # 깨진 데이터
            for _ in range(length):
                out.append(out[-dist])
    return bytes(out)


def _trailing_size(data: bytes, flags: int) -> int:
    """본문 레코드 끝에 붙은 부가 정보(다국어 겹침 등)의 바이트 수."""
    def entry(end: int) -> int:
        bitpos = result = 0
        while True:
            v = data[end - 1]
            result |= (v & 0x7F) << bitpos
            bitpos += 7
            end -= 1
            if (v & 0x80) or bitpos >= 28 or end == 0:
                return result
    num = 0
    f = flags >> 1
    while f:
        if f & 1 and len(data) - num > 0:
            num += entry(len(data) - num)
        f >>= 1
    if flags & 1 and len(data) - num > 0:
        num += (data[len(data) - num - 1] & 0b11) + 1
    return num


def _text_stream(pdb: _Pdb, hdr: _Header):
    """본문 레코드를 풀어 차례로 돌려준다(압축 방식이 1 또는 2일 때만 부를 것)."""
    for i in range(1, min(hdr.text_records, pdb.count - 1) + 1):
        raw = pdb.read(i)
        raw = raw[:len(raw) - _trailing_size(raw, hdr.extra_flags)] if hdr.extra_flags else raw
        yield _palmdoc_decompress(raw) if hdr.compression == 2 else raw


def _referenced(pdb: _Pdb, hdr: _Header) -> Optional[List[int]]:
    """본문이 이미지를 부르는 순서대로 이미지 번호(1부터). 본문을 풀 수 없으면 None."""
    if hdr.compression not in (1, 2):
        return None
    stream = _text_stream(pdb, hdr)
    order: List[int] = []
    seen = set()
    carry = b""
    kf8 = hdr.version >= 8
    for chunk in stream:
        text = carry + chunk
        # 레코드 경계에서 태그가 끊길 수 있어 뒤 200바이트를 다음 조각 앞에 붙여 다시 본다(이미 센 번호는 seen이 거른다)
        for m in (_EMBED if kf8 else _RECINDEX).finditer(text):
            n = int(m.group(1), 32) if kf8 else int(m.group(1))
            if n >= 1 and n not in seen:
                seen.add(n)
                order.append(n)
        carry = text[-200:]
    return order


def _open(path: str):
    try:
        f = open(path, "rb")
    except OSError as e:
        raise BookError(f"파일을 열 수 없습니다: {e}")
    try:
        pdb = _Pdb(f, os.path.getsize(path))
        hdr = _Header(pdb.read(0))
    except Exception:
        f.close()
        raise
    return f, pdb, hdr


def estimate_bytes(path: str) -> int:
    try:
        f, pdb, hdr = _open(path)
        with f:
            start = hdr.first_image if 0 < hdr.first_image < pdb.count else 1
            return sum(pdb.size(i) for i in range(start, pdb.count) if _image_ext(pdb.read(i, 8)))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def extract_mobi(path: str, on_progress: ProgressFn = noop_progress, to_ram: bool = False) -> List[ExtractedImage]:
    f, pdb, hdr = _open(path)
    with f:
        if hdr.encryption != 0:
            raise BookError("저작권 보호(DRM)가 걸린 책이라 열지 않습니다.")
        first = hdr.first_image
        results = ExtractResult()
        if not (0 < first < pdb.count):
            return results                                # 이미지 레코드가 없는 책(글만 있음) - 부르는 쪽이 "이미지가 들어 있지 않습니다"로 알린다
        thumb = hdr.exth_int(202)
        cover = hdr.exth_int(201)
        order = _referenced(pdb, hdr)
        if order is None:
            results.notes.append("본문 압축 방식(허프만)을 풀지 못해 이미지를 파일에 저장된 순서대로 가져왔습니다. 책 순서와 다를 수 있습니다.")
            order = []
        refs = [n for n in order if first + n - 1 < pdb.count]
        if cover is not None and first + cover < pdb.count and (cover + 1) not in refs[:1]:
            refs = [cover + 1] + [n for n in refs if n != cover + 1]
        if not refs:                                      # 부른 이미지가 없으면 이미지 레코드를 저장된 순서대로
            refs = [i - first + 1 for i in range(first, pdb.count) if i - first != thumb]
        picks = []
        for n in refs:
            idx = first + n - 1
            ext = _image_ext(pdb.read(idx, 12))
            if ext and pdb.size(idx) > 0:
                picks.append((n, idx, ext))
        if sum(pdb.size(idx) for _, idx, _ in picks) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        total = len(picks)
        for done, (n, idx, ext) in enumerate(picks, start=1):
            if pdb.size(idx) > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): image_{n:05d}")
            data = pdb.read(idx)
            label = f"image_{n:05d}{ext}"
            if to_ram:
                results.append(ExtractedImage(label=label, data=data))
            else:
                out_path = temp_store.new_path(ext)
                try:
                    with open(out_path, "wb") as out:
                        out.write(data)
                except OSError as e:
                    raise BookError(f"'{label}'을(를) 읽지 못했습니다: {e}")
                results.append(ExtractedImage(label=label, path=out_path))
            on_progress(done, total)
        return results
