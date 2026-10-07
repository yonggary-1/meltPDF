"""
이미지 -> PDF (용지 없이, 이미지 크기 = 페이지 크기) 핵심 로직.
GUI(tkinter)와 분리해서 독립적으로 테스트 가능하도록 작성.

중요한 설계 원칙(사용자 확인됨):
- 기존 PDF를 "열어서 편집"할 때, 그 PDF의 원본 페이지 내용(텍스트/벡터/이미지 해상도 등)은
  절대 다시 그리거나 손상시키지 않는다. 화면 목록에 보여줄 작은 미리보기 썸네일만 별도로
  렌더링하고, 실제 내보내기(export_pdf)는 원본 페이지 객체를 pikepdf로 그대로 복사해 넣는다
  (순서 변경/삭제만 반영, 페이지 내용 자체는 원본과 100% 동일).
- 새로 추가한 "이미지 파일"만 새 PDF 페이지로 변환(무용지, 이미지 크기 그대로)된다. 기존 PDF에서
  가져온 페이지는 이 변환 대상이 아니다.
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image, ImageOps

import img2pdf
import pikepdf
import fitz  # PyMuPDF

THUMB_MAX = 160          # 리스트에 보여줄 썸네일 최대 변 길이(px)
PREVIEW_RENDER_MAX_PX = 320  # 기존 PDF 페이지 미리보기를 렌더링할 때 최대 변 길이
                              # (화면 표시 전용 - 내보내기 결과물의 화질과는 무관함)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


@dataclass
class PageItem:
    """PDF의 한 페이지를 표현.

    kind='image'  : 사용자가 직접 추가한 이미지 파일. source_path(원본 그대로, 무손실) 또는
                     raster_bytes(EXIF 회전 등으로 재인코딩된 PNG)를 실제 내보내기에 사용.
    kind='pdf_page': 기존 PDF에서 가져온 페이지. 실제 내보내기에는 origin_pdf/origin_page_no로
                     원본 페이지 객체를 그대로 복사해 사용하고, raster_bytes는 쓰지 않는다
                     (썸네일 표시에만 쓰는 thumb_bytes와는 별개).
    """
    id: str
    label: str                     # UI에 표시할 이름
    kind: str                      # 'image' | 'pdf_page'
    width: int                     # kind='image': 이미지 픽셀 폭 / kind='pdf_page': 원본 페이지 폭(pt)
    height: int                    # 위와 동일 기준의 높이
    thumb_bytes: bytes             # UI 미리보기용 작은 PNG (항상 존재, 내보내기에는 사용 안 함)
    source_path: Optional[str] = None   # kind='image'이고 무손실 임베드 가능할 때 원본 경로
    raster_bytes: Optional[bytes] = None  # kind='image'이고 재인코딩이 필요할 때만 사용(PNG bytes)
    origin_pdf: Optional[str] = None      # kind='pdf_page'일 때 원본 pdf 경로 (내보내기 시 실제로 사용)
    origin_page_no: Optional[int] = None  # kind='pdf_page'일 때 1-based 페이지 번호 (내보내기 시 실제로 사용)


def _make_thumb_bytes(im: Image.Image) -> bytes:
    thumb = im.copy()
    thumb.thumbnail((THUMB_MAX, THUMB_MAX))
    buf = io.BytesIO()
    # 썸네일은 화면 표시용이므로 RGB로 통일해서 저장(투명 배경은 흰색으로)
    if thumb.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", thumb.size, (255, 255, 255))
        rgba = thumb.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        thumb = bg
    else:
        thumb = thumb.convert("RGB")
    thumb.save(buf, format="PNG")
    return buf.getvalue()


def load_image_item(path: Union[str, Path]) -> PageItem:
    """이미지 파일 하나를 PageItem으로 변환.

    EXIF Orientation이 없는(=1) 일반적인 경우는 원본 파일을 그대로(무손실) 재사용하고,
    회전 정보가 있는 경우에만 픽셀을 회전시켜 PNG로 다시 인코딩한다(화질 손실 없음, 파일만 커짐).
    """
    path = str(path)
    with Image.open(path) as im:
        return _build_image_item(im, Path(path).name, source_path=path, original_bytes=None)


def load_image_item_from_bytes(data: bytes, label: str) -> PageItem:
    """메모리에 있는 이미지 원본 바이트로 PageItem을 만든다(압축/책 파일에서 꺼낸 이미지를 디스크에
    쓰지 않고 RAM에 둘 때). 회전 정보가 없으면 원본 바이트를 그대로 내보내기에 쓴다(무손실)."""
    with Image.open(io.BytesIO(data)) as im:
        return _build_image_item(im, label, source_path=None, original_bytes=data)


def _build_image_item(im: Image.Image, label: str, source_path: Optional[str],
                      original_bytes: Optional[bytes]) -> PageItem:
    orientation = im.getexif().get(0x0112, 1)  # 1 = normal
    transposed = ImageOps.exif_transpose(im)
    width, height = transposed.size
    thumb_bytes = _make_thumb_bytes(transposed)

    if orientation in (1, None):
        # 회전 필요 없음 -> 원본 그대로 사용(완전 무손실, 재인코딩 없음)
        return PageItem(
            id=str(uuid.uuid4()),
            label=label,
            kind="image",
            width=width,
            height=height,
            thumb_bytes=thumb_bytes,
            source_path=source_path,
            raster_bytes=original_bytes,
        )
    # 회전 반영한 픽셀을 PNG로 저장(무손실 포맷, 화질 저하 없음)
    buf = io.BytesIO()
    save_im = transposed.convert("RGB") if transposed.mode in ("P",) else transposed
    save_im.save(buf, format="PNG")
    return PageItem(
        id=str(uuid.uuid4()),
        label=label,
        kind="image",
        width=width,
        height=height,
        thumb_bytes=thumb_bytes,
        raster_bytes=buf.getvalue(),
    )


def list_images_in_folder(folder: Union[str, Path]) -> List[str]:
    folder = Path(folder)
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    files.sort(key=lambda p: p.name.lower())
    return [str(p) for p in files]


def load_pdf_items(pdf_path: Union[str, Path]) -> List[PageItem]:
    """기존 PDF를 열어 각 페이지를 목록에 추가할 PageItem으로 변환.

    화면에 보여줄 작은 미리보기(thumb_bytes)만 렌더링하고, 원본 페이지 내용은 전혀 건드리지
    않는다 - 실제 내보내기(export_pdf)는 origin_pdf/origin_page_no로 원본 페이지 객체를 그대로
    복사해 넣는다(순서 변경/삭제만 반영, 텍스트/벡터/이미지 해상도 등 원본과 100% 동일).
    """
    pdf_path = str(pdf_path)
    items: List[PageItem] = []
    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc):
            rect = page.rect
            longest = max(rect.width, rect.height, 1)
            scale = PREVIEW_RENDER_MAX_PX / longest
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            with Image.open(io.BytesIO(pix.tobytes("png"))) as im:
                thumb_bytes = _make_thumb_bytes(im)
            items.append(
                PageItem(
                    id=str(uuid.uuid4()),
                    label=f"{Path(pdf_path).name} - p{i + 1}",
                    kind="pdf_page",
                    width=round(rect.width),
                    height=round(rect.height),
                    thumb_bytes=thumb_bytes,
                    origin_pdf=pdf_path,
                    origin_page_no=i + 1,
                )
            )
    finally:
        doc.close()
    return items


def _export_source(item: PageItem) -> Union[str, bytes]:
    if item.raster_bytes is not None:
        return item.raster_bytes
    return item.source_path  # type: ignore[return-value]


def export_pdf(
    items: List[PageItem],
    output_path: Union[str, Path],
    cover_id: Optional[str] = None,
) -> None:
    """items를 순서대로(단, cover_id가 있으면 그 항목을 맨 앞으로) PDF로 내보낸다.

    - kind='image' 항목: 무용지(페이지 크기 = 이미지 픽셀 크기) 페이지로 새로 변환.
    - kind='pdf_page' 항목: 원본 PDF의 그 페이지 객체를 pikepdf로 그대로 복사(재인코딩/래스터화
      없음 - 원본과 100% 동일한 내용으로 들어감). 순서 변경이나 페이지 삭제만 반영된다.
    """
    if not items:
        raise ValueError("내보낼 페이지가 없습니다.")

    ordered = list(items)
    if cover_id is not None:
        cover_items = [it for it in ordered if it.id == cover_id]
        rest = [it for it in ordered if it.id != cover_id]
        if cover_items:
            ordered = cover_items + rest

    output = pikepdf.Pdf.new()
    open_handles: List[pikepdf.Pdf] = []   # output.save()가 끝날 때까지 원본/임시 Pdf를 열어둬야 함
    src_cache: dict[str, pikepdf.Pdf] = {}  # 같은 원본 PDF에서 여러 페이지를 가져올 때 재사용

    try:
        for item in ordered:
            if item.kind == "pdf_page":
                src_pdf = src_cache.get(item.origin_pdf)
                if src_pdf is None:
                    src_pdf = pikepdf.open(item.origin_pdf)
                    src_cache[item.origin_pdf] = src_pdf
                    open_handles.append(src_pdf)
                output.pages.append(src_pdf.pages[item.origin_page_no - 1])
            else:
                source = _export_source(item)
                page_pdf_bytes = img2pdf.convert([source])
                tmp_pdf = pikepdf.open(io.BytesIO(page_pdf_bytes))
                open_handles.append(tmp_pdf)
                output.pages.append(tmp_pdf.pages[0])

        output.save(output_path)
    finally:
        output.close()
        for h in open_handles:
            try:
                h.close()
            except Exception:
                pass
