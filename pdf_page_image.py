"""
PDF 쪽이 "이미지 한 장을 놓은 쪽"인지 가려서, 그렇다면 그 이미지를 꺼낸다(v0.20.1, 사용자 요청). 아니면 그 이유를 돌려준다(v0.21.0).

PDF를 불러올 때(pdf_loader.py) 쪽마다 classify()를 한다.
- 이미지 한 장을 놓은 쪽 -> 그 이미지(파일 안의 원래 바이트)를 꺼내 이미지 항목으로 넣는다.
  PDF로 내보내면 다른 이미지처럼 이미지 크기의 쪽이 된다(원래 쪽 크기와 여백은 따르지 않음). 스캔본에 넣어 둔
  보이지 않는 글자(OCR 검색용)는 따라가지 않는다(사용자 확인).
- 90도 단위로 돌려 놓은 이미지(쪽 회전 포함, v0.21.0): JPEG는 바이트를 그대로 두고 "돌려서 보여라"는 표시(PageItem.rotate)만 붙인다
  (PDF로는 쪽 회전, 이미지로는 EXIF 회전 정보). 그 밖의 형식은 픽셀을 돌려 PNG로(무손실).
- 그 밖의 쪽은 예전처럼 쪽 그대로 넣고(원본 쪽을 손대지 않고 복사), 이유(page_reasons.py의 번호와 자세한 내용)를 남긴다.
  화면에서는 파란 테두리와 [?]로 이유를 보여 준다.

"이미지 한 장을 놓은 쪽"의 조건(하나라도 어긋나면 쪽 그대로 - 괄호 안은 이유 번호):
1. 이미지는 90도 단위로만 돌아 있고 뒤집히거나 비스듬하지 않음(flipped/skewed), 가로세로 비율이 놓인 칸과 같음(stretched).
2. 이미지가 쪽 밖으로 나가지 않고(outside), 잘라내기(clip)로 가려진 부분이 없음(clipped).
3. 그려지는 것: 이미지 한 장(no_image/multi_image/inline_image) + 보이지 않는 글자(또는 공백 문자만 있는 글자 - v0.21.0)뿐.
   보이는 글자는 drawn_text, 그 밖의 그림은 drawn_other. 이미지보다 먼저 칠한 흰 바탕(또는 불투명 이미지에 완전히 가려지는 도형)은 괜찮다.
4. 주석/양식 필드 없음(annot).
5. 이미지 자체: 마스크(/Mask, /ImageMask), /Decode 없음, 색 공간은 보통 것(회색/RGB/CMYK/ICC/색인) - image_format.
   투명 마스크(SMask)는 합쳐서 투명 PNG로 꺼낸다(pdf_images.read_image).
6. 암호가 걸렸거나 내용 복사를 막은 PDF는 모든 쪽을 쪽 그대로(locked - 이미지 내보내기와 같은 원칙).
화면(tkinter)은 모른다.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

import pdf_core
import pdf_images

TOL = 1.0                     # 좌표 비교 허용 오차(pt)
RATIO_TOL = 0.01              # 가로세로 비율 허용 오차(1%)
_PLAIN_CS = {"DeviceGray", "DeviceRGB", "DeviceCMYK", "CalGray", "CalRGB", "ICCBased", "Indexed"}


@dataclass
class Result:
    """판정 결과. data가 있으면 이미지로 꺼냄(ext, rotate), 없으면 쪽 그대로(reason, detail)."""
    data: Optional[bytes] = None
    ext: str = ""
    rotate: int = 0               # 시계 방향(0/90/180/270) - JPEG를 바이트 그대로 둘 때만 0이 아님
    reason: str = ""
    detail: str = ""
    xref: int = 0                 # 꺼낸(또는 그려진) 이미지
    shape: Optional[tuple] = None # 화면(PDF)에서 보이던 이미지 칸의 (폭, 높이) pt - 쪽 회전 반영


class _Page(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def can_extract(doc) -> bool:
    """이미지를 꺼내도 되는 PDF인가(암호 없음, 내용 복사 허용)."""
    try:
        return not doc.needs_pass and bool(doc.permissions & fitz.PDF_PERM_COPY)
    except Exception:
        return False


# 판정은 통과했지만 사용자가 고르게 하는 이유(v0.21.0): 쪽 그대로 넣고 [?] 창에서 해결 방법을 고른다.
# classify(allow=...)에 넣으면 그 이유는 무시하고 꺼낸다(해결 방법이 그렇게 부른다 - page_fixes.py).
SOFT = ("unused_images", "stretched")


def classify(doc, page, allow=()) -> Result:
    shape = None
    xref = 0
    try:
        xref, rotate, shape, soft = _simple_image(doc, page)
        for reason, detail in soft:
            if reason not in allow:
                raise _Page(reason, detail)
        got = pdf_images.read_image(doc, xref)
        if got is None:
            raise _Page("read_fail", "PDF 안의 이미지 데이터를 꺼내지 못했습니다.")
        data, ext = got
        if ext == ".jpg":
            return Result(data=data, ext=ext, rotate=rotate, xref=xref, shape=shape)   # 바이트 그대로 + 회전 표시(EXIF 회전은 따르지 않음)
        if rotate or _exif_rotated(data):
            data, ext = _rotated_png(data, rotate), ".png"         # 픽셀을 돌려 PNG로(무손실)
        return Result(data=data, ext=ext, xref=xref, shape=shape)
    except _Page as p:
        return Result(reason=p.reason, detail=p.detail, xref=xref, shape=shape)
    except Exception as e:                       # 판정 중 무슨 일이 있어도 쪽 그대로 넣으면 된다
        return Result(reason="error", detail=f"{type(e).__name__}: {e}", xref=xref, shape=shape)


def extract(doc, page):
    """(예전 호환) 이미지로 꺼낼 수 있으면 (바이트, 확장자), 아니면 None."""
    r = classify(doc, page)
    return (r.data, r.ext) if r.data is not None else None


def _rotation(a, b, c, d) -> Optional[int]:
    """이미지 배치 행렬 -> 시계 방향 회전(0/90/180/270). 뒤집힘이면 -1, 비스듬하면 None."""
    eps = 1e-3 * max(abs(a), abs(b), abs(c), abs(d), 1e-9)
    if abs(b) <= eps and abs(c) <= eps:
        if a > 0 and d > 0:
            return 0
        if a < 0 and d < 0:
            return 180
        return -1
    if abs(a) <= eps and abs(d) <= eps:
        if b > 0 and c < 0:
            return 90
        if b < 0 and c > 0:
            return 270
        return -1
    return None


def _simple_image(doc, page):
    """조건에 맞으면 (이미지 xref, 시계 방향 회전, 보이던 칸 (폭, 높이), 고르게 할 이유들[(이유, 자세히)]), 아니면 _Page(이유)."""
    if page.first_annot is not None or page.first_widget is not None:
        raise _Page("annot")
    infos = page.get_image_info()                # (xrefs=True는 이미지를 풀어 대조하느라 느려서 쓰지 않는다)
    images = page.get_images(full=True)
    if not infos:
        raise _Page("no_image")
    if len(infos) > 1:
        raise _Page("multi_image", f"이 쪽에 그려지는 이미지: {len(infos)}장")
    soft = []
    info = infos[0]
    if not images:
        raise _Page("inline_image")
    if len(images) == 1:
        xref = images[0][0]
        size = (images[0][2], images[0][3])
    else:
        # 그려지는 것은 1장인데 쪽 정보에 이미지가 여러 장 등록됨(여러 쪽이 이미지 목록을 함께 쓰는 PDF 등).
        # 어느 것이 그려지는지는 xrefs=True로만 알 수 있다(느리지만 이런 쪽에서만).
        xref = page.get_image_info(xrefs=True)[0].get("xref", 0)
        size = next(((im[2], im[3]) for im in images if im[0] == xref), None)
        soft.append(("unused_images", f"그려지는 이미지는 1장이지만, 쪽 정보에 등록된 이미지가 {len(images)}장입니다."))
    if not xref or size != (info.get("width"), info.get("height")):
        raise _Page("inline_image")
    a, b, c, d, _e, _f = info["transform"]
    rot = _rotation(a, b, c, d)
    if rot is None:
        raise _Page("skewed")
    if rot < 0:
        raise _Page("flipped")
    box = fitz.Rect(info["bbox"])
    area = fitz.Rect(0, 0, page.cropbox.width, page.cropbox.height)   # 쪽 회전 전 좌표(이미지 위치와 같은 기준)
    if not _inside(box, area):
        raise _Page("outside", f"이미지 {_r(box)}, 쪽 {_r(area)}")
    w, h = info.get("width") or 0, info.get("height") or 0
    if rot in (90, 270):
        w, h = h, w
    if not w or not h:
        raise _Page("read_fail", "이미지 크기를 알 수 없습니다.")
    shape = (box.height, box.width) if page.rotation % 180 else (box.width, box.height)
    if abs((w / h) / (box.width / box.height) - 1) > RATIO_TOL:
        rw, rh = info.get("width"), info.get("height")
        ow, oh = (rh, rw) if (rot + page.rotation) % 180 else (rw, rh)    # 화면 방향으로 본 원본 픽셀 크기
        soft.append(("stretched", f"원본 이미지 {ow}x{oh}px(비율 {ow / oh:.3f}), "
                                  f"PDF에서 보이던 칸 {shape[0]:.0f}x{shape[1]:.0f}pt(비율 {shape[0] / shape[1]:.3f})"))
    why = _image_format_problem(doc, xref)
    if why:
        raise _Page("image_format", why)
    has_alpha = _key(doc, xref, "SMask")[0] != "null"
    _only_image_drawn(page, box, has_alpha)
    return xref, (rot + page.rotation) % 360, shape, soft


def _r(rect) -> str:
    return f"({rect.x0:.0f}, {rect.y0:.0f})-({rect.x1:.0f}, {rect.y1:.0f})"


def _only_image_drawn(page, box, has_alpha: bool) -> None:
    log = page.get_bboxlog()
    kinds = [k for k, _r in log]
    at = kinds.index("fill-image") if "fill-image" in kinds else -1
    if at < 0:
        raise _Page("image_format", "이미지가 모양틀(마스크) 방식으로 그려집니다.")
    blank_text = None
    others = []
    for i, k in enumerate(kinds):
        if k in ("fill-image", "ignore-text"):
            continue
        if k in ("fill-text", "stroke-text"):
            if blank_text is None:
                blank_text = _text_is_blank(page)
            if blank_text:
                continue                         # 빈칸 글자뿐(워드가 문단 끝에 남기는 공백 등) - 그려지는 것이 없다
            raise _Page("drawn_text", _visible_text_sample(page))
        if k in ("fill-path", "stroke-path") and i < at:
            continue                             # 이미지보다 먼저 그린 도형 - 아래에서 흰 바탕/가려짐인지 본다
        others.append(k)
    if others:
        raise _Page("drawn_other", _describe(others))
    for dr in page.get_drawings(extended=True):
        kind = dr.get("type")
        if kind == "clip":
            sc = dr.get("scissor")
            if sc is not None and not _inside(box, fitz.Rect(sc)):
                raise _Page("clipped", f"이미지 {_r(box)}, 보이는 영역 {_r(fitz.Rect(sc))}")
            continue
        if kind == "group" and dr.get("blendmode", "Normal") == "Normal" and dr.get("opacity", 1.0) >= 0.999:
            continue                             # 보통 묶음(투명 이미지를 그릴 때 생김) - 보이는 결과는 이미지 그대로
        if kind in ("f", "s", "fs"):
            r = dr.get("rect")
            hidden = r is not None and not has_alpha and _inside(fitz.Rect(r), box)
            white = kind == "f" and _is_white(dr.get("fill"))
            if hidden or white:
                continue
            raise _Page("drawn_other", "이미지 아래(또는 옆)에 선이나 도형이 있습니다.")
        raise _Page("drawn_other", "투명도나 혼합 효과가 걸린 묶음이 있습니다." if kind == "group" else f"그림 요소: {kind}")


_KIND_NAMES = {"fill-path": "칠한 도형", "stroke-path": "선", "fill-shade": "그러데이션", "fill-imgmask": "모양틀 이미지",
               "fill-image": "이미지"}


def _describe(kinds) -> str:
    counts = {}
    for k in kinds:
        name = _KIND_NAMES.get(k, k)
        counts[name] = counts.get(name, 0) + 1
    return "이미지 위(또는 뒤)에 그려지는 것: " + ", ".join(f"{n} {c}개" for n, c in counts.items())


def _text_is_blank(page) -> bool:
    """보이는 글자(보이지 않음 방식이 아닌 것)가 모두 공백 문자인가."""
    try:
        for span in page.get_texttrace():
            if span.get("type") == 3:            # 보이지 않는 글자(OCR 검색용)
                continue
            if any(not chr(c[0]).isspace() for c in span.get("chars", ())):
                return False
        return True
    except Exception:
        return False


def _visible_text_sample(page, limit: int = 60) -> str:
    try:
        chars = []
        for span in page.get_texttrace():
            if span.get("type") != 3:
                chars.extend(chr(c[0]) for c in span.get("chars", ()))
        text = " ".join("".join(chars).split())
        return f"보이는 글자: \"{text[:limit]}{'…' if len(text) > limit else ''}\"" if text else ""
    except Exception:
        return ""


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


def _image_format_problem(doc, xref: int) -> str:
    """이미지 자체의 설정 때문에 꺼낼 수 없으면 그 설명, 괜찮으면 빈 문자열."""
    if _key(doc, xref, "ImageMask")[1] == "true":
        return "이미지가 모양틀(마스크)입니다."
    if _key(doc, xref, "Mask")[0] != "null":
        return "이미지에 투명 처리용 마스크(/Mask)가 붙어 있습니다."
    if _key(doc, xref, "Decode")[0] != "null" and not _adobe_inverted_cmyk(doc, xref):
        return "이미지에 색 반전/변환 설정(/Decode)이 있습니다."
    kind, value = _key(doc, xref, "ColorSpace")
    if kind == "null":
        return ""                                # JPEG2000은 색 공간을 이미지 안에 둔다
    if kind == "xref":
        try:
            value = doc.xref_object(int(value.split()[0]), compressed=True)
        except Exception:
            return "색 공간 정보를 읽지 못했습니다."
    first = value.strip().lstrip("[").split()[0] if value.strip() else ""
    name = first.lstrip("/").rstrip("]")
    return "" if name in _PLAIN_CS else f"특수한 색 공간({name})입니다."


def _adobe_inverted_cmyk(doc, xref: int) -> bool:
    """반전된 CMYK JPEG(포토샵 등): PDF의 /Decode [1 0 1 0 1 0 1 0]과 같은 반전 표시(Adobe)가 JPEG 안에도 있으면
    원본 바이트 그대로 꺼내도 같게 보이고, 다시 PDF로 넣으면 img2pdf가 같은 /Decode를 붙인다(v0.21.0 시험: 픽셀 차이 0)."""
    try:
        kind, value = doc.xref_get_key(xref, "Decode")
        if kind != "array" or value.replace(" ", "") != "[10101010]":
            return False
        head = (doc.xref_stream_raw(xref) or b"")[:65536]
        if not head.startswith(b"\xff\xd8"):
            return False
        k = head.find(b"\xff\xee")                      # APP14 덩어리: FF EE, 길이 2바이트, "Adobe"
        while k >= 0:
            if head[k + 4:k + 9] == b"Adobe":
                return True
            k = head.find(b"\xff\xee", k + 2)
        return False
    except Exception:
        return False


def _exif_rotated(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.getexif().get(0x0112, 1) not in (1, None)
    except Exception:
        return False


def _rotated_png(data: bytes, rotate: int) -> bytes:
    """(JPEG가 아닌 이미지) 픽셀을 시계 방향으로 돌린 PNG. 원본의 EXIF 회전은 따르지 않는다(PDF가 따르지 않으므로)."""
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        out = pdf_core.rotate_image(im, rotate)
        if out is im:
            out = im.copy()
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


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
