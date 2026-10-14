"""
깨진 이미지 머리 부분 복구 - 이미지 라이브러리가 형식을 알아보지 못하는(파일 앞부분이 깨진) PNG/JPEG에서
크기를 찾아내고, 머리 부분을 표준값으로 다시 써서 다시 읽을 수 있게 해 본다(v0.19.6, 사용자 요청).

- PNG: 파일은 항상 "서명 8바이트 + IHDR 덩어리(길이 4, 이름 4, 폭 4, 높이 4, ...)"로 시작한다.
  IHDR가 다른 곳에서 보이면 거기서, 아니면 표준 위치(16~23바이트)에서 폭/높이를 읽는다. IHDR의 검사값(CRC)이 맞으면
  그 크기를 믿는다. 앞 16바이트를 표준값으로 다시 쓴 데이터를 돌려준다.
- JPEG: 크기는 SOF 표시(FF C0~CF, C4/C8/CC 제외) 안에 있다. 파일 안에서 SOF를 찾아 크기를 읽고,
  맨 앞 시작 표시(FF D8)가 깨졌으면 FF D8을 다시 붙인 데이터를 돌려준다.
- 형식 짐작: 확장자, 그리고 파일 안의 표시(IHDR/IDAT, JPEG 표시들).
돌려준 데이터를 실제로 읽어 보는 것은 부르는 쪽(damaged_image.recover)이 한다. 여기는 바이트만 다룬다.
"""
from __future__ import annotations

import struct
import zlib
from typing import List, Optional, Tuple

PNG_SIG = b"\x89PNG\r\n\x1a\n"
MAX_SIDE = 100_000          # 이보다 큰 폭/높이는 잘못 읽은 값으로 본다


def _ok_size(w: int, h: int) -> bool:
    return 0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE


def guess_format(data: bytes, name: str = "") -> Optional[str]:
    low = name.lower()
    if b"IHDR" in data[:64] or b"IDAT" in data[:1 << 16]:
        return "png"
    if low.endswith(".png"):
        return "png"
    if any(m in data[:1 << 16] for m in (b"\xff\xdb", b"\xff\xc4", b"\xff\xda")) or low.endswith((".jpg", ".jpeg", ".jfif")):
        return "jpeg"
    return None


def png_size(data: bytes) -> Optional[Tuple[int, int]]:
    i = data.find(b"IHDR", 0, 4096)
    if i >= 4 and len(data) >= i + 17:
        w, h = struct.unpack(">II", data[i + 4:i + 12])
        crc = struct.unpack(">I", data[i + 17:i + 21])[0] if len(data) >= i + 21 else None
        if _ok_size(w, h) and (crc is None or zlib.crc32(data[i:i + 17]) & 0xffffffff == crc):
            return w, h
    if len(data) >= 33:                                  # IHDR 이름까지 깨졌으면 표준 위치에서
        w, h = struct.unpack(">II", data[16:24])
        crc = struct.unpack(">I", data[29:33])[0]
        if _ok_size(w, h) and zlib.crc32(b"IHDR" + data[16:29]) & 0xffffffff == crc:
            return w, h
    return None


def png_repair(data: bytes) -> Optional[bytes]:
    if len(data) < 33:
        return None
    i = data.find(b"IHDR", 0, 4096)
    if i >= 4:
        body = data[i - 4:]                              # IHDR 덩어리 길이부터
        return PNG_SIG + body
    return PNG_SIG + struct.pack(">I", 13) + b"IHDR" + data[16:]


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    k = 0
    n = len(data)
    while True:
        k = data.find(b"\xff", k)
        if k < 0 or k + 9 > n:
            return None
        m = data[k + 1]
        if m in _SOF:
            length = struct.unpack(">H", data[k + 2:k + 4])[0]
            h, w = struct.unpack(">HH", data[k + 5:k + 9])
            if 8 <= length <= 1024 and _ok_size(w, h):
                return w, h
        k += 1


def jpeg_repairs(data: bytes) -> List[bytes]:
    """다시 읽어 볼 후보들(앞에서부터 시도)."""
    out = []
    if not data.startswith(b"\xff\xd8"):
        out.append(b"\xff\xd8" + data[2:])               # 시작 표시만 깨진 경우
        for marker in (b"\xff\xe0", b"\xff\xe1", b"\xff\xdb", b"\xff\xc4", b"\xff\xc0", b"\xff\xc2"):
            k = data.find(marker, 0, 1 << 16)
            if k > 0:
                out.append(b"\xff\xd8" + data[k:])       # 첫 표시 앞을 버리고 시작 표시를 붙인다
                break
    return out


def analyze(data: bytes, name: str = "") -> Tuple[Optional[Tuple[int, int]], List[bytes]]:
    """(찾아낸 크기 또는 None, 다시 읽어 볼 데이터 후보들)."""
    fmt = guess_format(data, name)
    if fmt == "png":
        rep = png_repair(data)
        return png_size(data), ([rep] if rep else [])
    if fmt == "jpeg":
        return jpeg_size(data), jpeg_repairs(data)
    return None, []
