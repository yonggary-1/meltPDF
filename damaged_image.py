"""
손상된(중간에 끊기거나 일부가 깨진) 이미지를 "읽을 수 있는 부분만이라도" 불러오는 기능.

보통 이미지 읽기(pdf_core)는 데이터가 모자라면 오류를 내므로, 그 이미지는 목록에 못 들어온다.
여기서는 읽을 수 있는 부분까지만 디코딩해서(나머지는 비어 있음) 무손실 PNG로 다시 담아 목록에 넣는다.
- 목록에 보이는 모습과 PDF로 내보낸 모습이 같다(깨진 원본 바이트를 그대로 넣으면 PDF 변환이 실패하는 PNG가 있어서 PNG로 담는다).
- 파일 맨 앞(머리 부분)이 깨져서 이미지로 인식조차 안 되는 등 전혀 읽을 수 없는 파일은 unreadable_item()으로
  "X 표시 상자" 썸네일을 단 항목을 만든다(v0.19.6, 사용자 요청: 못 읽는 파일도 무조건 목록에 넣는다). 원본 바이트는 그대로
  들고 있어 이미지 내보내기는 원본 파일을 그대로 저장하고, PDF에는 그 자리에 빈 쪽이 들어간다(pdf_core._fit_blank_pages).
- 깨진 데까지 읽는 동안에는 다른 스레드의 이미지 풀기를 멈춘다(decode_guard.exclusive - 그 사이 다른 깨진 이미지가
  검출되지 않고 통과하던 문제, v0.19.6).
이 모듈은 "손상된 것을 어떻게 읽나"만 맡고, 어떤 파일이 손상됐는지 알리는 일은 부르는 쪽이 한다.
"""
from __future__ import annotations

import io
from typing import Optional

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

import decode_guard
import pdf_core


def open_tolerant(data: Optional[bytes] = None, path: Optional[str] = None) -> Image.Image:
    """손상된 이미지를 읽을 수 있는 부분까지 디코딩해 PIL 이미지로 돌려준다(EXIF 회전 반영). 못 읽으면 예외."""
    with decode_guard.exclusive():           # Pillow의 전역 설정을 잠깐만 바꾼다 - 그동안 다른 스레드는 이미지를 풀지 않는다
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
        return "이미지 머리 부분이 깨졌거나 이미지 파일이 아닙니다"
    if isinstance(exc, OSError) and not isinstance(exc, (FileNotFoundError, PermissionError)):
        return "이미지 데이터가 깨져 읽지 못했습니다"
    if isinstance(exc, FileNotFoundError):
        return "파일을 찾지 못했습니다"
    if isinstance(exc, PermissionError):
        return "파일을 열 권한이 없습니다"
    return "읽지 못했습니다"


_PLACEHOLDER: Optional[bytes] = None


def placeholder_thumb() -> bytes:
    """전혀 못 읽은 이미지의 썸네일: 빈 상자에 X자(PNG). 한 번 만들어 같이 쓴다."""
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        from PIL import ImageDraw
        s = 4                                           # 크게 그려 줄여서 선을 매끄럽게
        w, h = 120, pdf_core.THUMB_MAX
        im = Image.new("RGB", (w * s, h * s), (255, 255, 255))
        d = ImageDraw.Draw(im)
        line = (150, 150, 150)
        d.rectangle([1 * s, 1 * s, (w - 2) * s, (h - 2) * s], outline=line, width=2 * s)
        d.line([(2 * s, 2 * s), ((w - 3) * s, (h - 3) * s)], fill=line, width=2 * s)
        d.line([((w - 3) * s, 2 * s), (2 * s, (h - 3) * s)], fill=line, width=2 * s)
        im = im.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        _PLACEHOLDER = buf.getvalue()
    return _PLACEHOLDER


def unreadable_item(label: str, data: Optional[bytes] = None, path: Optional[str] = None,
                    reason: str = "") -> pdf_core.PageItem:
    """전혀 못 읽는 이미지 파일도 목록에 넣는 항목: 썸네일은 X 표시 상자, 빨간 테두리(damaged), 크기는 모름(0).
    원본은 그대로 들고 있다(data 또는 path) - 이미지 내보내기는 원본을 그대로 저장, PDF에는 그 자리에 빈 쪽."""
    import os
    import uuid
    try:
        empty = (len(data) == 0) if data is not None else (bool(path) and os.path.getsize(path) == 0)
    except OSError:
        empty = False
    if empty and (not reason or reason == unreadable_reason(UnidentifiedImageError())):
        reason = "빈 파일(0바이트)입니다"
    item = pdf_core.PageItem(id=str(uuid.uuid4()), label=label, kind="image", width=0, height=0,
                             thumb_bytes=placeholder_thumb(), source_path=path if data is None else None,
                             raster_bytes=data, damaged=True, unreadable=True)
    item.unreadable_reason = reason
    if data is None and path:
        try:
            item._disk_bytes = os.path.getsize(path)
        except OSError:
            item._disk_bytes = 0
    return item


def recover(label: str, data: Optional[bytes] = None, path: Optional[str] = None,
            exc: Optional[Exception] = None) -> pdf_core.PageItem:
    """보통 읽기도, 깨진 데까지 읽기도 실패한 이미지의 마지막 시도(v0.19.6):
    1) 머리 부분을 표준값으로 다시 써서(header_repair) 다시 읽는다 - 다 풀리면 그대로, 일부만 풀리면 깨진 이미지로 넣는다
       (어느 쪽이든 손상 표시는 남기고 repaired=True. 내보내기에는 복구한 데이터를 쓴다).
    2) 그래도 안 되면 X 표시 항목. 크기만이라도 찾았으면 그 크기를 적어 둔다(PDF의 빈 쪽 크기로 씀)."""
    import header_repair
    reason = unreadable_reason(exc) if exc is not None else ""
    raw = data
    if raw is None and path:
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            raw = None
    size = None
    if raw:
        size, candidates = header_repair.analyze(raw, label)
        for cand in candidates:
            try:
                item = pdf_core.load_image_item_from_bytes(cand, label)
            except Exception:
                try:
                    item = load_damaged_item(label, data=cand)
                except Exception:
                    continue
            item.label = label
            item.damaged = True
            item.repaired = True
            return item
    item = unreadable_item(label, data=data, path=path, reason=reason)
    if size:
        item.width, item.height = size
        item.size_found = True                       # 머리 부분에서 크기만 찾아냄(그림은 못 풂)
    return item
