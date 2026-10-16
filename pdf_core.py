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
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

from PIL import Image, ImageOps

import img2pdf
import pikepdf
import fitz  # PyMuPDF

import decode_guard
import margin_trim
import pdf_meta

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
    damaged: bool = False                 # 깨진 이미지(읽을 수 있는 부분만 표시, 또는 전혀 못 읽음) - 화면에서 빨간 테두리로 구분
    unreadable: bool = False              # 전혀 못 읽은 이미지 파일(썸네일은 X 표시 상자). 원본 바이트는 그대로 들고 있고 PDF에는 그 자리에 빈 쪽이 들어간다
    page_images: Optional[dict] = None    # kind='pdf_page'일 때 그 쪽에 쓰인 이미지들 {xref: 저장 크기(바이트)} - 용량 표시용(size_info.py)
    # PDF 쪽에서 꺼낸 이미지(v0.21.0): 원본 바이트의 픽셀을 시계 방향으로 이만큼(0/90/180/270) 돌려 보여 준다. 바이트는 그대로 두고
    # PDF로 내보낼 때는 쪽 회전(/Rotate), 이미지로 내보낼 때는 EXIF 회전 정보로 나타낸다. 원본에 든 EXIF 회전은 따르지 않는다
    # (PDF가 따르지 않으므로). None이면 보통 이미지 파일(EXIF 회전은 불러올 때 PNG로 반영).
    rotate: Optional[int] = None
    # PDF에서 보이던 비율로 꺼낸 이미지(v0.21.0, [?] 창에서 고름): 화면 방향의 (폭, 높이) 비율. PDF로 내보낼 때 쪽을 이 비율로
    # 만들고 이미지를 그 칸에 맞춰 늘린다(바이트는 그대로). 이미지로 내보내면 원본 비율 그대로다. None이면 원본 비율.
    shape: Optional[tuple] = None


def _make_thumb_bytes(im: Image.Image, in_place: bool = False) -> bytes:
    """화면 목록용 작은 썸네일(PNG). in_place=True면 im을 직접 줄인다(복사하지 않아 빠름 - 부르는 쪽이 im을 더 쓰지 않을 때만).

    빠르게 만드는 방법(v0.18.0): JPEG는 draft로 처음부터 1/2~1/8 크기로 풀고(원본 전체를 풀지 않음), 줄일 때는 reducing_gap으로
    정수배 축소를 먼저 한다. 흑백(1비트)과 팔레트 그림은 회색/RGBA로 바꾼 뒤 줄여 계단 현상을 줄인다. PNG 압축은 빠른 단계(1)."""
    thumb = im if in_place else im.copy()
    if in_place and getattr(thumb, "format", None) == "JPEG":
        try:
            thumb.draft(thumb.mode, (THUMB_MAX * 2, THUMB_MAX * 2))
        except Exception:
            pass
    if thumb.mode == "1":
        thumb = thumb.convert("L")
    elif thumb.mode == "P":
        thumb = thumb.convert("RGBA")
    elif thumb.mode in ("I", "F") or thumb.mode.startswith("I;"):
        # 16비트 흑백 PNG/TIFF 등(스캔본에 있음): 그대로는 줄이기가 안 되므로(예전에는 오류가 나 "손상된 이미지"로 잘못 표시됨)
        # 8비트 회색으로 바꾼다. 값이 255를 넘으면 16비트 범위로 보고 비율을 맞춘다.
        t = thumb if thumb.mode == "F" else thumb.convert("I")
        hi = t.getextrema()[1] or 0
        scale = 255.0 / (65535.0 if hi > 255 else 255.0)
        thumb = t.point(lambda v: v * scale).convert("L")
    thumb.thumbnail((THUMB_MAX, THUMB_MAX), reducing_gap=2.0)
    buf = io.BytesIO()
    # 썸네일은 화면 표시용이므로 RGB로 통일해서 저장(투명 배경은 흰색으로)
    if thumb.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGB", thumb.size, (255, 255, 255))
        rgba = thumb.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        thumb = bg
    else:
        thumb = thumb.convert("RGB")
    thumb.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def load_image_item(path: Union[str, Path]) -> PageItem:
    """이미지 파일 하나를 PageItem으로 변환.

    EXIF Orientation이 없는(=1) 일반적인 경우는 원본 파일을 그대로(무손실) 재사용하고,
    회전 정보가 있는 경우에만 픽셀을 회전시켜 PNG로 다시 인코딩한다(화질 손실 없음, 파일만 커짐).
    """
    path = str(path)
    with decode_guard.shared(), Image.open(path) as im:      # 깨진 이미지 풀기와 겹치지 않게(decode_guard.py)
        item = _build_image_item(im, Path(path).name, source_path=path, original_bytes=None)
    if item.source_path:
        # 상태 표시줄 용량 계산(size_info)이 화면 스레드에서 파일 크기를 묻지 않게, 읽는 김에 여기서(일꾼 스레드) 재 둔다.
        # 윈도우에서는 파일 크기 묻기가 느릴 수 있어 수천 장이면 화면이 버벅였다(v0.19.3).
        try:
            item._disk_bytes = os.path.getsize(path)
        except OSError:
            pass
    return item


def load_image_item_from_bytes(data: bytes, label: str) -> PageItem:
    """메모리에 있는 이미지 원본 바이트로 PageItem을 만든다(압축/책 파일에서 꺼낸 이미지를 디스크에
    쓰지 않고 RAM에 둘 때). 회전 정보가 없으면 원본 바이트를 그대로 내보내기에 쓴다(무손실)."""
    with decode_guard.shared(), Image.open(io.BytesIO(data)) as im:
        return _build_image_item(im, label, source_path=None, original_bytes=data)


def load_fixed_image_item(label: str, rotate: int, data: Optional[bytes] = None,
                          path: Optional[str] = None, shape: Optional[tuple] = None) -> PageItem:
    """PDF 쪽에서 꺼낸 이미지 항목(rotate, shape - PageItem 참고). 원본 바이트(data) 또는 그 사본 파일(path)을 그대로 쓴다."""
    rotate = rotate % 360
    with decode_guard.shared(), Image.open(io.BytesIO(data) if data is not None else path) as im:
        width, height = im.size
        thumb_bytes = _make_thumb_bytes(im, in_place=True)
    if rotate:
        thumb_bytes = _rotate_png(thumb_bytes, rotate)
        if rotate in (90, 270):
            width, height = height, width
    if shape:
        height = max(1, round(width * shape[1] / shape[0]))
        thumb_bytes = _reshape_png(thumb_bytes, shape)
    item = PageItem(id=str(uuid.uuid4()), label=label, kind="image", width=width, height=height,
                    thumb_bytes=thumb_bytes, source_path=path if data is None else None,
                    raster_bytes=data, rotate=rotate, shape=tuple(shape) if shape else None)
    if data is None and path:
        try:
            item._disk_bytes = os.path.getsize(path)
        except OSError:
            pass
    return item


_T = getattr(Image, "Transpose", Image)          # Pillow 9.1 이전에는 Image.ROTATE_90 등
ROTATE_TRANSPOSE = {90: _T.ROTATE_270, 180: _T.ROTATE_180, 270: _T.ROTATE_90}


def rotate_image(im: Image.Image, rotate: Optional[int]) -> Image.Image:
    """시계 방향으로 rotate(0/90/180/270)도 돌린 그림(픽셀 그대로 옮김, 0이나 None이면 그대로)."""
    t = ROTATE_TRANSPOSE.get((rotate or 0) % 360)
    return im.transpose(t) if t is not None else im


def reshape_image(im: Image.Image, shape: Optional[tuple]) -> Image.Image:
    """화면에 보여 줄 때만: 폭은 그대로 두고 높이를 shape(폭, 높이) 비율에 맞춰 늘이거나 줄인 그림."""
    if not shape:
        return im
    h = max(1, round(im.width * shape[1] / shape[0]))
    return im if h == im.height else im.resize((im.width, h), Image.LANCZOS)


def _reshape_png(png: bytes, shape: tuple) -> bytes:
    with Image.open(io.BytesIO(png)) as im:
        im.load()
        out = reshape_image(im, shape)
        buf = io.BytesIO()
        out.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _rotate_png(png: bytes, rotate: int) -> bytes:
    with Image.open(io.BytesIO(png)) as im:
        out = rotate_image(im, rotate)
        buf = io.BytesIO()
        out.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _build_image_item(im: Image.Image, label: str, source_path: Optional[str],
                      original_bytes: Optional[bytes]) -> PageItem:
    orientation = im.getexif().get(0x0112, 1)  # 1 = normal

    if orientation in (1, None):
        # 회전 필요 없음 -> 원본 그대로 사용(완전 무손실, 재인코딩 없음). 크기는 머리에서 읽고, 썸네일만 작게 풀어 만든다
        # (원본 전체를 풀지 않음 - 내보내기는 원본 파일/바이트를 그대로 쓰므로 결과와 무관).
        width, height = im.size
        thumb_bytes = _make_thumb_bytes(im, in_place=True)
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
    transposed = ImageOps.exif_transpose(im)
    width, height = transposed.size
    thumb_bytes = _make_thumb_bytes(transposed)
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


def list_images_in_folder(folder: Union[str, Path], recursive: bool = False, should_stop=None) -> List[str]:
    """폴더 안의 이미지 파일 경로들을 이름 순(자연 정렬: 2가 10보다 앞, 압축 파일과 같은 규칙)으로 돌려준다.
    recursive이면 하위 폴더의 이미지도 모두 넣는다(폴더 단위로 비교 - 같은 폴더 파일끼리 모임). should_stop()이 참이 되면 찾기를 멈춘다. 맥이 만드는
    __MACOSX 폴더와 "._" 파일은 뺀다. 바로가기(심볼릭 링크) 폴더는 따라가지 않는다."""
    from natural_sort import path_key
    folder = Path(folder)
    found: List[Tuple[str, str]] = []                      # (정렬용 상대 경로, 전체 경로)
    if recursive:
        for dirpath, dirnames, filenames in os.walk(folder):
            if should_stop is not None and should_stop():     # [중단]
                break
            dirnames[:] = [d for d in dirnames if d != "__MACOSX"]
            for name in filenames:
                if not name.startswith("._") and Path(name).suffix.lower() in IMAGE_EXTS:
                    full = Path(dirpath) / name
                    found.append((full.relative_to(folder).as_posix(), str(full)))
    else:
        for p in folder.iterdir():
            if p.is_file() and not p.name.startswith("._") and p.suffix.lower() in IMAGE_EXTS:
                found.append((p.name, str(p)))
    found.sort(key=lambda pair: path_key(pair[0]))
    return [full for _rel, full in found]


def load_pdf_items(pdf_path: Union[str, Path]) -> List[PageItem]:
    """기존 PDF를 열어 각 페이지를 목록에 추가할 PageItem(kind='pdf_page')으로 변환.
    (화면의 PDF 불러오기는 v0.20.1부터 pdf_loader.py가 한다 - 이미지 한 장뿐인 쪽은 이미지로 꺼냄. 이 함수는 모든 쪽을 쪽으로.)"""
    pdf_path = str(pdf_path)
    doc = fitz.open(pdf_path)
    try:
        return [pdf_page_item(doc, page, pdf_path, i) for i, page in enumerate(doc)]
    finally:
        doc.close()


def pdf_page_item(doc, page, pdf_path: str, index: int) -> PageItem:
    """PDF의 한 쪽 -> 목록 항목(kind='pdf_page').

    화면에 보여줄 작은 미리보기(thumb_bytes)만 렌더링하고, 원본 페이지 내용은 전혀 건드리지
    않는다 - 실제 내보내기(export_pdf)는 origin_pdf/origin_page_no로 원본 페이지 객체를 그대로
    복사해 넣는다(순서 변경/삭제만 반영, 텍스트/벡터/이미지 해상도 등 원본과 100% 동일).
    """
    rect = page.rect
    longest = max(rect.width, rect.height, 1)
    scale = PREVIEW_RENDER_MAX_PX / longest
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    with Image.open(io.BytesIO(pix.tobytes("png"))) as im:
        thumb_bytes = _make_thumb_bytes(im)
    page_images = {}
    try:
        for info in page.get_images(full=True):
            xref = info[0]
            if xref and xref not in page_images:
                page_images[xref] = _stream_length(doc, xref)
    except Exception:
        pass                                    # 용량 표시용일 뿐이라 못 읽어도 불러오기는 계속한다
    return PageItem(
        id=str(uuid.uuid4()),
        label=f"{Path(pdf_path).name} - p{index + 1}",
        kind="pdf_page",
        width=round(rect.width),
        height=round(rect.height),
        thumb_bytes=thumb_bytes,
        origin_pdf=pdf_path,
        origin_page_no=index + 1,
        page_images=page_images,
    )


def _stream_length(doc, xref: int) -> int:
    """PDF 안 이미지 하나가 차지하는 저장 크기(압축된 그대로의 바이트 수). 사전의 Length를 먼저 보고, 없으면 직접 읽는다."""
    try:
        kind, value = doc.xref_get_key(xref, "Length")
        if kind == "int":
            return int(value)
        return len(doc.xref_stream_raw(xref) or b"")
    except Exception:
        return 0


def _export_source(item: PageItem) -> Union[str, bytes]:
    if item.raster_bytes is not None:
        return item.raster_bytes
    return item.source_path  # type: ignore[return-value]


# 이미지 페이지를 PDF로 바꿀 때 한 번에 묶는 양. 묶음마다 임시 파일 하나로 만들고 그 파일을 열어 쓰므로,
# 메모리에는 한 묶음(최대 이 크기)만 올라가고 나머지는 디스크에서 필요할 때 읽는다(책 전체가 메모리에 한꺼번에 올라가지 않음).
CHUNK_MAX_BYTES = 96 * 1024 * 1024
CHUNK_MAX_PAGES = 200


def _source_size(source: Union[str, bytes]) -> int:
    if isinstance(source, bytes):
        return len(source)
    try:
        return os.path.getsize(source)
    except OSError:
        return 0


def _fit_blank_pages(output, blank_fit: List[int]) -> None:
    """못 읽은 이미지 자리의 빈 쪽 크기를 바로 앞 쪽과 같게(맨 앞이면 바로 뒤의 보통 쪽과 같게) 맞춘다. 회전(/Rotate)도 따른다.
    앞 쪽이 또 다른 빈 쪽이면 이미 맞춘 그 크기를 따른다(앞에서부터 차례로 맞춤)."""
    fit = set(blank_fit)
    n = len(output.pages)
    for idx in sorted(fit):
        src = idx - 1 if idx > 0 else next((j for j in range(idx + 1, n) if j not in fit), None)
        if src is None:
            continue                                    # 모든 쪽이 빈 쪽 - 기본 크기(A4) 그대로
        sp = pikepdf.Page(output.pages[src])
        dp = pikepdf.Page(output.pages[idx])
        dp.obj.MediaBox = pikepdf.Array([float(v) for v in sp.mediabox])
        rot = sp.obj.get("/Rotate")
        if rot is not None:
            dp.obj.Rotate = int(rot)


def _reshape_page(pdf, page, shape: tuple, rotate: int) -> None:
    """img2pdf가 만든 이미지 한 장짜리 쪽을, 화면 방향 비율 shape(폭, 높이)의 쪽으로 바꾼다. 폭은 그대로, 높이만 바꾸고
    이미지는 그 칸을 꽉 채우게 늘인다(이미지 데이터는 그대로). 쪽 회전(rotate)이 90/270이면 비율을 돌려서 계산한다."""
    box = [float(v) for v in page.obj.MediaBox]
    w = box[2] - box[0]
    sw, sh = shape
    if rotate % 180:
        sw, sh = sh, sw
    h = w * sh / sw
    name = next(iter(page.obj.Resources.XObject.keys()))
    page.obj.MediaBox = pikepdf.Array([0, 0, w, h])
    for key in ("/CropBox", "/TrimBox", "/BleedBox", "/ArtBox"):
        if key in page.obj:
            del page.obj[key]
    page.obj.Contents = pdf.make_stream(f"q {w:.4f} 0 0 {h:.4f} 0 0 cm {name} Do Q".encode("ascii"))


def export_pdf(
    items: List[PageItem],
    output_path: Union[str, Path],
    cover_id: Optional[str] = None,
    meta=None,
    trim_margins: bool = False,
) -> int:
    """items를 순서대로(단, cover_id가 있으면 그 항목을 맨 앞으로) PDF로 내보낸다.
    meta(book_meta.BookMeta)가 있으면 서지 정보(문서 정보 + XMP)로 넣는다(pdf_meta.apply_meta).
    trim_margins면 쪽 그대로 넣는 PDF 쪽의 흰 여백을 잘라 보이는 영역만 좁힌다(margin_trim.py - 내용은 그대로). 돌려주는 값은 여백을 자른 쪽 수.

    - kind='image' 항목: 무용지(페이지 크기 = 이미지 픽셀 크기) 페이지로 새로 변환.
    - kind='pdf_page' 항목: 원본 PDF의 그 페이지 객체를 pikepdf로 그대로 복사(재인코딩/래스터화
      없음 - 원본과 100% 동일한 내용으로 들어감). 순서 변경이나 페이지 삭제만 반영된다.

    메모리: 이미지 페이지는 연속된 것끼리 묶어서(CHUNK_*) 임시 파일 PDF로 만든 뒤 그 페이지들을 결과에 옮긴다. 페이지마다 PDF 바이트를
    통째로 메모리에 쥐고 있던 이전 방식은 이미지 총량의 약 2배를 썼고, 이 방식은 약 1배(= 결과 PDF 크기)를 쓴다(측정은 CHANGELOG).
    1배 아래로는 못 내린다: pikepdf가 페이지를 다른 PDF로 옮길 때 이미지 데이터를 메모리로 복사하고(파일을 mmap으로 열어도 같음을
    확인함), img2pdf도 만드는 동안 이미지를 메모리에 둔다. 결과 PDF는 이전과 같다(img2pdf가 페이지마다 같은 규칙으로 만든다).
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
    tmp_dir = tempfile.mkdtemp(prefix="meltpdf_")
    chunk_no = 0

    def flush(pending: List[tuple]):
        """모인 이미지들을 임시 PDF 파일 하나로 만들어 그 페이지들을 output에 이어 붙인다."""
        nonlocal chunk_no
        if not pending:
            return
        chunk_no += 1
        tmp_path = os.path.join(tmp_dir, f"chunk{chunk_no}.pdf")
        with open(tmp_path, "wb") as f:
            # 원본에 든 EXIF 회전은 따르지 않는다: 보통 이미지는 불러올 때 이미 반영했고(PNG), PDF에서 꺼낸 이미지는 PDF가 따르지 않으므로.
            img2pdf.convert([p[0] for p in pending], outputstream=f, rotation=img2pdf.Rotation.none)
        tmp_pdf = pikepdf.open(tmp_path)
        open_handles.append(tmp_pdf)
        start = len(output.pages)
        output.pages.extend(tmp_pdf.pages)
        for k, (_src, rot, shape) in enumerate(pending):
            page = output.pages[start + k]
            if shape:                                  # PDF에서 보이던 비율로(v0.21.0): 쪽과 이미지 칸을 그 비율로
                _reshape_page(output, page, shape, rot)
            if rot:                                    # PDF에서 돌려 놓여 있던 이미지: 바이트는 그대로, 쪽 회전으로(v0.21.0)
                page.obj.Rotate = int(rot)
        pending.clear()

    blank_fit: List[int] = []              # 크기를 앞(또는 뒤) 쪽에 맞출 빈 쪽 번호(0부터)
    fitz_cache: dict = {}                   # 여백 찾기용으로 연 원본 PDF(PyMuPDF)
    trimmed = 0
    try:
        pending: List[tuple] = []                # (이미지 원본, 쪽 회전, 보일 비율)
        pending_bytes = 0
        for item in ordered:
            if item.kind == "pdf_page":
                flush(pending)
                pending_bytes = 0
                src_pdf = src_cache.get(item.origin_pdf)
                if src_pdf is None:
                    src_pdf = pikepdf.open(item.origin_pdf)
                    src_cache[item.origin_pdf] = src_pdf
                    open_handles.append(src_pdf)
                output.pages.append(src_pdf.pages[item.origin_page_no - 1])
                if trim_margins:
                    fdoc = fitz_cache.get(item.origin_pdf)
                    if fdoc is None:
                        fdoc = fitz_cache[item.origin_pdf] = fitz.open(item.origin_pdf)
                    box = margin_trim.content_box(fdoc[item.origin_page_no - 1])
                    if box is not None:
                        margin_trim.apply(output.pages[-1], box)
                        trimmed += 1
            elif item.unreadable:
                # 전혀 못 읽은 이미지: 그 자리에 빈 쪽(v0.19.6). 머리에서 크기를 찾았으면 그 크기(96dpi 기준 - 보통 이미지와 같은 규칙),
                # 아니면 바로 앞 쪽과 같은 크기(맨 앞이면 바로 뒤 쪽) - 크기는 모든 쪽을 넣은 뒤 맞춘다.
                flush(pending)
                pending_bytes = 0
                if getattr(item, "size_found", False) and item.width and item.height:
                    output.add_blank_page(page_size=(item.width * 72 / 96, item.height * 72 / 96))
                else:
                    blank_fit.append(len(output.pages))
                    output.add_blank_page(page_size=(595, 842))
            else:
                source = _export_source(item)
                size = _source_size(source)
                if pending and (pending_bytes + size > CHUNK_MAX_BYTES or len(pending) >= CHUNK_MAX_PAGES):
                    flush(pending)
                    pending_bytes = 0
                pending.append((source, item.rotate or 0, item.shape))
                pending_bytes += size
        flush(pending)
        _fit_blank_pages(output, blank_fit)

        pdf_meta.apply_meta(output, meta)
        output.save(output_path)
        return trimmed
    finally:
        output.close()
        for d in fitz_cache.values():
            d.close()
        for h in open_handles:
            try:
                h.close()
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)    # 열린 파일을 모두 닫은 뒤에 지운다(윈도우는 열린 파일을 지울 수 없다)
