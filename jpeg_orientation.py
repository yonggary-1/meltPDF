"""
JPEG 바이트에 EXIF 회전 정보(Orientation)만 써 넣기 - 그림 데이터는 한 바이트도 바꾸지 않는다(v0.21.0).

PDF에서 돌려 놓여 있던 JPEG를 이미지로 내보낼 때 쓴다(image_export). 픽셀을 돌리면 다시 압축해야 해 화질이 떨어지고,
JPEG 블록 단위로만 돌리는 무손실 회전도 그림 크기가 블록(8/16px)의 배수가 아니면 가장자리가 잘리거나 엉킨다.
그래서 머리 부분에 "시계 방향으로 N도 돌려서 보여라"는 표시만 넣는다(윈도우 사진 보기, 브라우저 등은 따름).

- 이미 EXIF가 있으면 그 안의 회전 값만 바꾼다(다른 EXIF 정보는 유지). 없으면 새 EXIF 덩어리를 시작 표시(또는 JFIF) 뒤에 넣는다.
- rotate 0이고 EXIF 회전 정보가 없으면 받은 바이트를 그대로 돌려준다.
- JPEG가 아니거나 구조를 읽지 못하면 받은 바이트를 그대로 돌려준다.
"""
from __future__ import annotations

import struct
from typing import Optional, Tuple

from PIL import Image

ORIENTATION_TAG = 0x0112
ROTATE_TO_ORIENTATION = {0: 1, 90: 6, 180: 3, 270: 8}


def with_orientation(data: bytes, rotate: int) -> bytes:
    value = ROTATE_TO_ORIENTATION.get(rotate % 360)
    if value is None or not data.startswith(b"\xff\xd8"):
        return data
    try:
        found = _find_exif(data)
        if found is not None:
            start, end = found                                  # APP1 덩어리 전체(표시 FF E1부터)
            exif = Image.Exif()
            exif.load(data[start + 4:end])
            if exif.get(ORIENTATION_TAG, 1) == value:
                return data
            exif[ORIENTATION_TAG] = value
            return data[:start] + _segment(exif) + data[end:]
        if value == 1:
            return data
        exif = Image.Exif()
        exif[ORIENTATION_TAG] = value
        at = _after_jfif(data)
        return data[:at] + _segment(exif) + data[at:]
    except Exception:
        return data


def _segment(exif) -> bytes:
    payload = exif.tobytes()
    if not payload.startswith(b"Exif\x00\x00"):
        payload = b"Exif\x00\x00" + payload
    if len(payload) + 2 > 0xFFFF:
        raise ValueError("EXIF가 너무 큼")
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _segments(data: bytes):
    """(표시 번호, 시작, 끝) - 그림 데이터(SOS) 전까지의 머리 덩어리들."""
    k = 2
    n = len(data)
    while k + 4 <= n and data[k] == 0xFF:
        marker = data[k + 1]
        if marker == 0xFF:                                      # 채움 바이트
            k += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            k += 2
            continue
        length = struct.unpack(">H", data[k + 2:k + 4])[0]
        yield marker, k, k + 2 + length
        if marker == 0xDA:                                      # 그림 데이터 시작 - 머리 끝
            return
        k += 2 + length


def _find_exif(data: bytes) -> Optional[Tuple[int, int]]:
    for marker, start, end in _segments(data):
        if marker == 0xE1 and data[start + 4:start + 10] == b"Exif\x00\x00":
            return start, end
    return None


def _after_jfif(data: bytes) -> int:
    for marker, start, end in _segments(data):
        if marker == 0xE0:
            return end                                          # JFIF(APP0) 바로 뒤
        break
    return 2                                                    # 시작 표시 바로 뒤


def orientation_of(data: bytes) -> int:
    """(시험/확인용) JPEG의 EXIF 회전 값(없으면 1)."""
    found = _find_exif(data) if data.startswith(b"\xff\xd8") else None
    if found is None:
        return 1
    exif = Image.Exif()
    exif.load(data[found[0] + 4:found[1]])
    return exif.get(ORIENTATION_TAG, 1)
