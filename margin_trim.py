"""
쪽 여백 없애기 - PDF로 내보낼 때, 쪽 그대로 넣은 PDF 쪽(kind='pdf_page')의 흰 여백을 잘라 낸다(v0.21.0, 사용자 요청).

- 쪽 내용은 한 바이트도 바꾸지 않는다. 보이는 영역(MediaBox/CropBox)만 내용이 있는 곳으로 좁힌다
  (원본 쪽을 손대지 않는다는 원칙 그대로 - 잘린 바깥은 보이지 않을 뿐 파일 안에 남아 있음).
- "내용이 있는 곳" = 쪽을 그렸을 때 흰색이 아닌 점들을 모두 감싸는 사각형(글자, 선, 이미지 무엇이든 보이는 그대로).
  2배(144dpi)로 그려서 찾으므로 오차는 0.5pt 정도다. 거의 흰색(밝기 250 이상)은 흰색으로 본다.
- 아무것도 없는(전부 흰) 쪽은 그대로 둔다.
- 켜고 끄는 것은 툴바의 체크 상자(설정에 기억 - trim_pdf_margins). 이미지 항목은 원래 여백이 없으므로 해당 없음.
"""
from __future__ import annotations

from typing import Optional, Tuple

import fitz  # PyMuPDF
import pikepdf
from PIL import Image

ZOOM = 2.0
WHITE = 250


def content_box(page) -> Optional[Tuple[float, float, float, float]]:
    """PyMuPDF 쪽 -> 내용이 있는 곳의 PDF 좌표 사각형(x0, y0, x1, y1). 전부 희거나 이미 여백이 없으면 None."""
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), colorspace=fitz.csGRAY, alpha=False)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    box = im.point(lambda v: 255 if v < WHITE else 0).getbbox()
    if box is None:
        return None
    x0, y0, x1, y1 = box
    if (x0, y0, x1, y1) == (0, 0, pix.width, pix.height):
        return None
    shown = fitz.Rect(x0 / ZOOM, y0 / ZOOM, x1 / ZOOM, y1 / ZOOM)          # 화면(쪽 회전 반영) 좌표
    pdf_rect = shown * page.derotation_matrix * ~page.transformation_matrix  # -> PDF 좌표(왼쪽 아래 원점)
    pdf_rect.normalize()
    return (pdf_rect.x0, pdf_rect.y0, pdf_rect.x1, pdf_rect.y1)


def apply(pike_page, box) -> None:
    """내보낼 PDF의 쪽(pikepdf) 보이는 영역을 box로."""
    arr = pikepdf.Array([round(v, 3) for v in box])
    pike_page.obj.MediaBox = arr
    pike_page.obj.CropBox = arr
    for key in ("/TrimBox", "/BleedBox", "/ArtBox"):
        if key in pike_page.obj:
            del pike_page.obj[key]
