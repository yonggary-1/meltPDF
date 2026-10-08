"""
손상된(중간에 끊기거나 일부가 깨진) 이미지를 "읽을 수 있는 부분만이라도" 불러오는 기능.

보통 이미지 읽기(pdf_core)는 데이터가 모자라면 오류를 내므로, 그 이미지는 목록에 못 들어온다.
여기서는 읽을 수 있는 부분까지만 디코딩해서(나머지는 비어 있음) 무손실 PNG로 다시 담아 목록에 넣는다.
- 목록에 보이는 모습과 PDF로 내보낸 모습이 같다(깨진 원본 바이트를 그대로 넣으면 PDF 변환이 실패하는 PNG가 있어서 PNG로 담는다).
- 파일 맨 앞(머리 부분)이 깨져서 이미지로 인식조차 안 되는 경우는 읽을 수 없으므로 오류를 그대로 낸다.
이 모듈은 "손상된 것을 어떻게 읽나"만 맡고, 어떤 파일이 손상됐는지 알리는 일은 부르는 쪽이 한다.
"""
from __future__ import annotations

import io
import threading
from typing import Optional

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

import pdf_core

_lock = threading.Lock()


def open_tolerant(data: Optional[bytes] = None, path: Optional[str] = None) -> Image.Image:
    """손상된 이미지를 읽을 수 있는 부분까지 디코딩해 PIL 이미지로 돌려준다(EXIF 회전 반영). 못 읽으면 예외."""
    with _lock:                              # Pillow의 전역 설정을 잠깐만 바꾼다(다른 이미지에 영향이 가지 않게)
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            with Image.open(io.BytesIO(data) if data is not None else path) as im:
                im.load()
                return ImageOps.exif_transpose(im)
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False


def load_damaged_item(label: str, data: Optional[bytes] = None, path: Optional[str] = None) -> pdf_core.PageItem:
    """data(메모리) 또는 path(파일)의 손상된 이미지를 읽을 수 있는 부분까지만 읽어 PageItem으로 만든다. 못 읽으면 예외."""
    im = open_tolerant(data, path)
    if im.mode not in ("1", "L", "LA", "RGB", "RGBA", "P"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    item = pdf_core.load_image_item_from_bytes(buf.getvalue(), label)
    item.label = label
    return item


def unreadable_reason(exc: Exception) -> str:
    """읽지 못한 이미지에 붙일 설명(사용자에게 보이는 글). Pillow의 영어 오류 문구를 그대로 보여주지 않는다."""
    if isinstance(exc, UnidentifiedImageError):
        return "손상되어 읽지 못했습니다(이미지 머리 부분이 깨졌거나 이미지 파일이 아닙니다). 목록에서 뺐습니다."
    return "손상되어 읽지 못했습니다. 목록에서 뺐습니다."
