"""
PDF 쪽이 "이미지 한 장을 그대로 놓은 쪽"인지 가려서, 그렇다면 그 이미지를 꺼낸다(v0.20.1, 사용자 요청).

PDF를 불러올 때(pdf_loader.py) 쪽마다 이 판정을 한다.
- 이미지 한 장을 그대로 놓은 쪽 -> 그 이미지(파일 안의 원래 바이트)를 꺼내 이미지 항목으로 넣는다.
  PDF로 내보내면 다른 이미지처럼 이미지 크기의 쪽이 된다(원래 쪽 크기와 여백은 따르지 않음). 스캔본에 넣어 둔
  보이지 않는 글자(OCR 검색용)는 따라가지 않는다(사용자 확인).
- 그 밖의 쪽(회전/뒤집기/잘라내기/늘리기, 이미지 여러 장, 보이는 글자, 선/도형, 주석, 특수한 색 공간이나 마스크 등)은
  예전처럼 쪽 그대로 넣는다(원본 쪽을 손대지 않고 복사).
- 암호가 걸렸거나 내용 복사를 막은 PDF는 이미지를 꺼내지 않고 모두 쪽 그대로 넣는다(이미지 내보내기와 같은 원칙).

"그대로 놓음"의 조건(하나라도 어긋나면 쪽 그대로):
1. 쪽 회전(/Rotate) 0, 이미지는 회전/뒤집기 없이 놓임, 이미지의 가로세로 비율이 놓인 칸과 같음(늘리지 않음).
2. 이미지가 쪽 밖으로 나가지 않고, 잘라내기(clip)로 가려진 부분이 없음.
3. 그려지는 것: 이미지 한 장 + 보이지 않는 글자뿐. 이미지보다 먼저 칠한 흰 바탕(또는 불투명 이미지에 완전히 가려지는 도형)은 괜찮다.
4. 주석/양식 필드 없음.
5. 이미지 자체: 마스크(/Mask, /ImageMask), /Decode 없음, 색 공간은 보통 것(회색/RGB/CMYK/ICC/색인). 투명 마스크(SMask)는
   합쳐서 투명 PNG로 꺼낸다(pdf_images.read_image). JPEG에 EXIF 회전 정보가 있으면 PDF와 다르게 보일 수 있어 쪽 그대로.
화면(tkinter)은 모른다.
"""
from __future__ import annotations

import io
import os
from typing import Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

import pdf_images

TOL = 1.0                     # 좌표 비교 허용 오차(pt)
RATIO_TOL = 0.01              # 가로세로 비율 허용 오차(1%)
_PLAIN_CS = {"DeviceGray", "DeviceRGB", "DeviceCMYK", "CalGray", "CalRGB", "ICCBased", "Indexed"}


def can_extract(doc) -> bool:
    """이미지를 꺼내도 되는 PDF인가(암호 없음, 내용 복사 허용)."""
    try:
        return not doc.needs_pass and bool(doc.permissions & fitz.PDF_PERM_COPY)
    except Exception:
        return False


def extract(doc, page) -> Optional[Tuple[bytes, str]]:
    """이 쪽이 이미지 한 장을 그대로 놓은 쪽이면 (원래 이미지 바이트, 확장자), 아니면 None."""
    try:
        xref = simple_image_xref(doc, page)
        if xref is None:
            return None
        got = pdf_images.read_image(doc, xref)
        if got is None or _exif_rotated(got[0]):
            return None
        return got
    except Exception:
        return None                              # 판정 중 무슨 일이 있어도 쪽 그대로 넣으면 된다


def simple_image_xref(doc, page) -> Optional[int]:
    """조건(머리말 1~5의 쪽 부분)에 맞으면 그 이미지의 xref, 아니면 None."""
    if page.rotation % 360:
        return None
    if page.first_annot is not None or page.first_widget is not None:
        return None
    infos = page.get_image_info()                # (xrefs=True는 이미지를 풀어 대조하느라 느려서 쓰지 않는다)
    images = page.get_images(full=True)
    if len(infos) != 1 or len(images) != 1:
        return None                              # 이미지 여러 장(쓰이지 않는 이미지가 같이 들어 있는 쪽도 그대로 둔다)
    info = infos[0]
    xref = images[0][0]
    if not xref or (images[0][2], images[0][3]) != (info.get("width"), info.get("height")):
        return None                              # 그려진 것이 쪽 안에 직접 쓴 작은 이미지(xref 없음)일 수 있음
    a, b, c, d, _e, _f = info["transform"]
    if a <= 0 or d <= 0 or abs(b) > 1e-3 * a or abs(c) > 1e-3 * d:
        return None                              # 회전 또는 뒤집기
    box = fitz.Rect(info["bbox"])
    if not _inside(box, page.rect):
        return None                              # 쪽 밖으로 나가 잘림
    w, h = info.get("width") or 0, info.get("height") or 0
    if not w or not h or abs((w / h) / (box.width / box.height) - 1) > RATIO_TOL:
        return None                              # 늘리거나 줄여 비율이 바뀜
    if not _plain_image(doc, xref):
        return None
    has_alpha = _key(doc, xref, "SMask")[0] != "null"
    if not _only_image_drawn(page, box, has_alpha):
        return None
    return xref


def _only_image_drawn(page, box, has_alpha: bool) -> bool:
    log = page.get_bboxlog()
    kinds = [k for k, _r in log]
    if kinds.count("fill-image") != 1:
        return False
    at = kinds.index("fill-image")
    for i, k in enumerate(kinds):
        if k in ("fill-image", "ignore-text"):
            continue
        if k in ("fill-path", "stroke-path") and i < at:
            continue                             # 이미지보다 먼저 그린 도형 - 아래에서 흰 바탕/가려짐인지 본다
        return False                             # 보이는 글자, 이미지 뒤의 도형, 음영, 마스크 이미지 등
    for dr in page.get_drawings(extended=True):
        kind = dr.get("type")
        if kind == "clip":
            sc = dr.get("scissor")
            if sc is not None and not _inside(box, fitz.Rect(sc)):
                return False                     # 이미지 일부가 잘려 보이지 않음
            continue
        if kind == "group" and dr.get("blendmode", "Normal") == "Normal" and dr.get("opacity", 1.0) >= 0.999:
            continue                             # 보통 묶음(투명 이미지를 그릴 때 생김) - 보이는 결과는 이미지 그대로
        if kind in ("f", "s", "fs"):
            r = dr.get("rect")
            hidden = r is not None and not has_alpha and _inside(fitz.Rect(r), box)
            white = kind == "f" and _is_white(dr.get("fill"))
            if hidden or white:
                continue
        return False                             # 그 밖의 도형, 투명 그룹 등
    return True


def _is_white(color) -> bool:
    return color is not None and len(color) in (1, 3, 4) and (
        all(v >= 0.999 for v in color) if len(color) != 4 else all(v <= 0.001 for v in color))


def _inside(inner, outer) -> bool:
    return (inner.x0 >= outer.x0 - TOL and inner.y0 >= outer.y0 - TOL
            and inner.x1 <= outer.x1 + TOL and inner.y1 <= outer.y1 + TOL)


def _key(doc, xref: int, name: str):
    try:
        return doc.xref_get_key(xref, name)
    except Exception:
        return ("null", "null")


def _plain_image(doc, xref: int) -> bool:
    if _key(doc, xref, "ImageMask")[1] == "true":
        return False
    if _key(doc, xref, "Mask")[0] != "null" or _key(doc, xref, "Decode")[0] != "null":
        return False
    kind, value = _key(doc, xref, "ColorSpace")
    if kind == "null":
        return True                              # JPEG2000은 색 공간을 이미지 안에 둔다
    if kind == "xref":
        try:
            value = doc.xref_object(int(value.split()[0]), compressed=True)
        except Exception:
            return False
    first = value.strip().lstrip("[").split()[0] if value.strip() else ""
    return first.lstrip("/").rstrip("]") in _PLAIN_CS


def _exif_rotated(data: bytes) -> bool:
    """JPEG 등에 EXIF 회전 정보가 있으면 True. PDF는 이 정보를 무시하므로, 이미지로 꺼내면 화면과 다르게 돌아갈 수 있다."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.getexif().get(0x0112, 1) not in (1, None)
    except Exception:
        return False                             # 못 여는 이미지는 부르는 쪽(항목 만들기)에서 걸러진다


def estimate_bytes(path: str) -> int:
    """이 PDF에서 꺼낼 수 있는 이미지 크기의 대략(파일 안 이미지들의 저장 크기 합, 파일 크기를 넘지 않음).
    메모리/디스크 중 어디에 둘지 정하는 데 쓴다."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0
    total = 0
    try:
        doc = fitz.open(path)
    except Exception:
        return 0
    try:
        if not can_extract(doc):
            return 0
        for x in range(1, doc.xref_length()):
            try:
                if doc.xref_get_key(x, "Subtype")[1] == "/Image":
                    kind, value = doc.xref_get_key(x, "Length")
                    total += int(value) if kind == "int" else 0
            except Exception:
                continue
    finally:
        doc.close()
    return min(total, size)
