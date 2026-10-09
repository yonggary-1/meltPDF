"""
PDF 안에 든 이미지 꺼내기 핵심 로직 - 화면(tkinter)을 모른다. [이미지 내보내기]가 목록의 PDF 쪽(kind='pdf_page')을 만났을 때 쓴다.

쪽을 그림으로 그리는 것이 아니라, 그 쪽에 쓰인 이미지 자체를 파일로 꺼낸다(zip에서 파일을 꺼내는 것과 같은 개념).
- 한 쪽에 이미지가 여러 장이면 그려지는 순서대로 모두 꺼낸다. 같은 이미지를 여러 쪽이 쓰면(예: 로고) 처음 나온 자리에서만 한 번 꺼낸다.
- JPEG는 PDF 안에 든 바이트 그대로 나온다(CMYK/흑백 JPEG 포함). JPEG2000도 그대로(.jp2). 그 밖의 형식(압축을 푼 픽셀, 흑백 스캔용
  압축 등)은 PyMuPDF가 풀어 같은 픽셀의 PNG로 돌려준다(무손실이지만 원래 바이트는 아니다).
- 회전/잘라내기 같은 쪽 설정은 반영하지 않는다: 저장된 이미지 그대로다(스캔본은 회전이 쪽 설정에 들어 있어 옆으로 누워 나올 수 있다).
- 투명 마스크(SMask)가 붙은 이미지는 마스크를 합쳐 투명 PNG로 꺼낸다(크기가 다르면 마스크 없이 이미지만).
- 암호가 필요하거나 내용 복사를 막아 둔 PDF는 꺼내지 않는다(우회하지 않는다).
"""
from __future__ import annotations

import io
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

_PNG_FROM_PYMUPDF = {"png", "bmp", "gif", "tiff", "tif"}


class PdfImageError(Exception):
    """사용자에게 그대로 보여줘도 되는 사유(한국어)를 담은 오류."""


def open_pdf(path: str):
    """꺼내도 되는 PDF만 연다. 열 수 없거나 암호/복사 제한이 있으면 PdfImageError."""
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise PdfImageError(f"PDF를 열지 못했습니다: {e}")
    if doc.needs_pass:
        doc.close()
        raise PdfImageError("암호가 걸린 PDF라 이미지를 꺼내지 않습니다.")
    if not (doc.permissions & fitz.PDF_PERM_COPY):
        doc.close()
        raise PdfImageError("내용 복사가 허용되지 않은 PDF라 이미지를 꺼내지 않습니다.")
    return doc


def page_xrefs(page) -> List[int]:
    """이 쪽에서 쓰는 이미지의 xref들: 그려지는 순서대로, 그 뒤에 쪽 자원에만 있는 것."""
    seen: List[int] = []
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref", 0)
        if xref and xref not in seen:
            seen.append(xref)
    for item in page.get_images(full=True):
        if item[0] not in seen:
            seen.append(item[0])
    return seen


def _single_filter(doc, xref: int) -> str:
    kind, value = doc.xref_get_key(xref, "Filter")
    if kind == "name":
        return value.lstrip("/")
    if kind == "array":
        names = [t.lstrip("/") for t in value.strip("[]").split()]
        if len(names) == 1:
            return names[0]
    return ""


def ext_hint(doc, xref: int) -> str:
    """꺼냈을 때의 확장자를 압축 방식만 보고 미리 짐작한다(.jpg / .jp2 / .png). 실제 확장자는 read_image가 돌려준다."""
    filt = _single_filter(doc, xref)
    return {"DCTDecode": ".jpg", "JPXDecode": ".jp2"}.get(filt, ".png")


def _with_alpha(doc, xref: int, smask: int, base_bytes: bytes) -> Optional[bytes]:
    try:
        mask_img = doc.extract_image(smask)
        with Image.open(io.BytesIO(base_bytes)) as base, Image.open(io.BytesIO(mask_img["image"])) as mask:
            if base.size != mask.size:
                return None
            out = base.convert("RGB")
            out.putalpha(mask.convert("L"))
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def read_image(doc, xref: int) -> Optional[Tuple[bytes, str]]:
    """(바이트, 확장자). 꺼낼 수 없으면 None."""
    filt = _single_filter(doc, xref)
    smask = 0
    try:
        info = doc.extract_image(xref)
        smask = (info or {}).get("smask", 0)
    except Exception:
        info = None
    if filt in ("DCTDecode", "JPXDecode") and not smask:
        raw = doc.xref_stream_raw(xref)              # PDF 안에 든 바이트 그대로(= 원래 이미지 파일)
        if raw:
            return raw, (".jpg" if filt == "DCTDecode" else ".jp2")
    if not info or not info.get("image"):
        return None
    data = info["image"]
    ext = (info.get("ext") or "").lower()
    if ext not in ("jpeg", "jpg", "png", "jpx", "jp2") and ext not in _PNG_FROM_PYMUPDF:
        try:                                        # 처음 보는 형식은 PyMuPDF가 픽셀로 풀어 PNG로
            data, ext = fitz.Pixmap(doc, xref).tobytes("png"), "png"
        except Exception:
            return None
    if smask:
        merged = _with_alpha(doc, xref, smask, data)
        if merged is not None:
            return merged, ".png"
    return data, {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "jpx": ".jp2", "jp2": ".jp2",
                  "bmp": ".bmp", "gif": ".gif", "tiff": ".tif", "tif": ".tif"}.get(ext, ".png")
