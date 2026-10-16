"""
쪽 그대로 넣은 PDF 쪽의 해결 방법들 - [?] 창(page_reason_dialog)의 버튼(v0.21.0, 사용자 요청. 원인별로 논의하며 하나씩 추가).

register()가 page_reasons.SOLUTIONS에 등록한다(app_window가 부름). 해결 방법은 그 쪽을 PDF에서 다시 읽어 이미지 항목으로 꺼내고, 목록에서
그 쪽 항목과 바꾼다(doc_model.replace - 같은 자리, 표지였으면 표지 유지). 바꾼 뒤에도 다른 이유가 남아 있으면 쪽 그대로 두고
이유만 새로 적은 뒤 [?] 창을 다시 연다.

지금 있는 해결 방법:
- 모든 원인: [쪽 그대로 두기] - 원본 쪽 그대로(지금 상태). 확인 표시로 [?]가 [✓]로 바뀐다(사용자 요청: 모든 보기에 있어야 함).
- 그려지는 이미지는 1장인데 쪽 정보에 여러 장 등록됨(unused_images):
  [그려진 이미지만 꺼내기] - 화면에 보이던 한 장만. / [등록된 이미지 모두 꺼내기] - 등록된 이미지를 모두 각각의 항목으로(그 자리에 차례로).
- 비율을 바꿔 놓은 이미지(stretched): 두 모습을 나란히 보여 주고 고른다.
  [PDF에서 보이던 비율로] - 바이트는 그대로, PDF로 내보낼 때 그 비율의 쪽으로(PageItem.shape). 이미지로 내보내면 원본 비율.
  [원본 비율로] - 원본 이미지 그대로.
"""
from __future__ import annotations

import io
from pathlib import Path
from tkinter import messagebox
from typing import List, Optional

import fitz  # PyMuPDF
from PIL import Image

import activity_log
import page_reasons
import pdf_core
import pdf_images
import pdf_page_image
import temp_store
from config import APP_TITLE
from page_reasons import Solution
from settings import STORAGE_DISK

PREVIEW = 220                     # 미리보기 긴 변(px)


# ---------------------------------------------------------- 공통
def _open_page(item):
    doc = fitz.open(item.origin_pdf)
    return doc, doc[item.origin_page_no - 1]


def _to_disk(app) -> bool:
    try:
        return app.settings.get("storage_mode") == STORAGE_DISK
    except Exception:
        return False


def _make_item(app, item, data: bytes, ext: str, rotate: int, suffix: str = "", shape=None, page_count: int = 0):
    label = f"{Path(item.origin_pdf).name} - p{item.origin_page_no}{suffix}{ext}"
    if _to_disk(app):
        tmp = temp_store.new_path(ext)
        with open(tmp, "wb") as f:
            f.write(data)
        new = pdf_core.load_fixed_image_item(label, rotate, path=tmp, shape=shape)
    else:
        new = pdf_core.load_fixed_image_item(label, rotate, data=data, shape=shape)
    new.label = label
    new.pdf_page_count = page_count
    return new


def _replace(app, item, new_items) -> bool:
    if not new_items:
        return False
    app.model.replace(item.id, new_items)
    activity_log.log(f"해결 방법: {item.label} -> {', '.join(n.label for n in new_items)}")
    return True


def _single(app, item, allow, shape_from_pdf: bool = False) -> bool:
    """classify(allow)로 다시 판정해 이미지 한 장으로 꺼낸다. 다른 이유가 남으면 이유만 새로 적고 창을 다시 연다."""
    doc, page = _open_page(item)
    try:
        r = pdf_page_image.classify(doc, page, allow=allow)
        count = doc.page_count
    finally:
        doc.close()
    if r.data is None:
        if r.reason and r.reason != item.pdf_reason:
            item.pdf_reason, item.pdf_reason_detail = r.reason, r.detail
            app.model._emit("structure")                 # 목록형 설명 줄 갱신
            app.root.after_idle(lambda: app._open_reason(item.id))
        else:
            messagebox.showwarning(APP_TITLE, "이미지를 꺼내지 못했습니다.\n" + (r.detail or page_reasons.title(r.reason)))
        return True
    try:
        new = _make_item(app, item, r.data, r.ext, r.rotate, shape=r.shape if shape_from_pdf else None, page_count=count)
    except Exception as e:
        messagebox.showwarning(APP_TITLE, f"꺼낸 이미지를 읽지 못했습니다:\n{e}")
        return False
    return _replace(app, item, [new])


# ---------------------------------------------------------- unused_images
def _drawn_only(app, item) -> bool:
    return _single(app, item, allow={"unused_images"})      # 비율도 다르면 이유가 "비율"로 바뀌고 창이 다시 열린다


def _all_registered(app, item) -> bool:
    doc, page = _open_page(item)
    try:
        r = pdf_page_image.classify(doc, page, allow=set(pdf_page_image.SOFT))     # 그려진 것(방향 포함)
        xrefs = [im[0] for im in page.get_images(full=True)]
        if r.xref in xrefs:
            xrefs.remove(r.xref)
            xrefs.insert(0, r.xref)                       # 그려진 것을 맨 앞에
        new, failed = [], []
        for k, x in enumerate(xrefs, 1):
            try:
                if x == r.xref and r.data is not None:
                    data, ext, rot = r.data, r.ext, r.rotate
                else:
                    got = pdf_images.read_image(doc, x)
                    if got is None:
                        failed.append(str(x))
                        continue
                    (data, ext), rot = got, 0
                new.append(_make_item(app, item, data, ext, rot, suffix=f"_{k}", page_count=doc.page_count))
            except Exception:
                failed.append(str(x))
    finally:
        doc.close()
    if failed:
        messagebox.showwarning(APP_TITLE, f"등록된 이미지 {len(failed)}장은 꺼내지 못해 뺐습니다.")
    return _replace(app, item, new)


def _preview_drawn(item) -> Optional[Image.Image]:
    return _preview_image_area(item)


def _preview_all(item) -> Optional[Image.Image]:
    doc, page = _open_page(item)
    try:
        thumbs: List[Image.Image] = []
        drawn = pdf_page_image.classify(doc, page, allow=set(pdf_page_image.SOFT)).xref
        xrefs = [im[0] for im in page.get_images(full=True)]
        xrefs.sort(key=lambda x: x != drawn)              # 꺼낼 때와 같은 순서(보이던 것이 맨 앞)
        for x in xrefs[:12]:
            got = pdf_images.read_image(doc, x)
            if got is None:
                continue
            try:
                with Image.open(io.BytesIO(got[0])) as pic:
                    pic.draft("RGB", (160, 160))
                    t = pic.convert("RGB")
                    t.thumbnail((100, 100))
                    thumbs.append(t)
            except Exception:
                continue
    finally:
        doc.close()
    if not thumbs:
        return None
    cols = min(4, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 104 + 4, rows * 104 + 4), (230, 230, 230))
    for i, t in enumerate(thumbs):
        r, c = divmod(i, cols)
        sheet.paste(t, (4 + c * 104 + (100 - t.width) // 2, 4 + r * 104 + (100 - t.height) // 2))
    sheet.thumbnail((PREVIEW, PREVIEW))
    return sheet


# ---------------------------------------------------------- stretched
def _as_pdf(app, item) -> bool:
    return _single(app, item, allow=set(pdf_page_image.SOFT), shape_from_pdf=True)   # (그려진 것만 꺼내기를 고른 뒤 넘어온 경우 포함)


def _as_original(app, item) -> bool:
    return _single(app, item, allow=set(pdf_page_image.SOFT))


def _preview_image_area(item) -> Optional[Image.Image]:
    """PDF에서 보이던 모습: 쪽에서 그 이미지가 놓인 칸만 그린 것."""
    doc, page = _open_page(item)
    try:
        infos = page.get_image_info()
        if not infos:
            return None
        clip = fitz.Rect(infos[0]["bbox"]) * page.rotation_matrix
        clip.normalize()
        z = PREVIEW / max(clip.width, clip.height, 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=clip, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def _preview_original(item) -> Optional[Image.Image]:
    """원본 이미지(화면 방향으로 돌린 것, 원래 비율)."""
    doc, page = _open_page(item)
    try:
        r = pdf_page_image.classify(doc, page, allow=set(pdf_page_image.SOFT))
    finally:
        doc.close()
    if r.data is None:
        return None
    with Image.open(io.BytesIO(r.data)) as pic:
        pic.draft("RGB", (PREVIEW * 2, PREVIEW * 2))
        im = pdf_core.rotate_image(pic.convert("RGB"), r.rotate)
    im.thumbnail((PREVIEW, PREVIEW))
    return im


# ---------------------------------------------------------- 모든 원인: 쪽 그대로 두기
def _keep(app, item) -> bool:
    """지금처럼 원본 쪽 그대로 쓴다. 확인했다는 표시로 [?]가 [✓]로 바뀐다(다시 눌러 다른 방법을 고를 수 있음)."""
    item.pdf_kept = True
    activity_log.log(f"쪽 그대로 두기: {item.label}")
    app.model._emit("structure")                     # 타일 다시 그리기([✓])
    return True


def _preview_page(item) -> Optional[Image.Image]:
    """쪽 그대로: 원본 쪽 전체."""
    doc, page = _open_page(item)
    try:
        z = PREVIEW / max(page.rect.width, page.rect.height, 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def register() -> None:
    page_reasons.KEEP = Solution("쪽 그대로 두기", "지금처럼 원본 쪽을 그대로 씁니다(PDF로 내보내면 원본 쪽 그대로, "
                                 "글자·선 등도 그대로). 확인했다는 표시로 [?]가 [✓]로 바뀝니다.", _keep, _preview_page)
    page_reasons.SOLUTIONS["unused_images"] = [
        Solution("그려진 이미지만 꺼내기", "화면에 보이던 한 장만 이미지로 꺼냅니다. 쪽에 등록만 되어 있던 나머지는 버립니다.",
                 _drawn_only, _preview_drawn),
        Solution("등록된 이미지 모두 꺼내기", "쪽에 등록된 이미지를 모두 각각의 항목으로 꺼내 이 자리에 차례로 넣습니다"
                 "(보이던 것이 맨 앞, 이름 끝에 _1, _2 …).", _all_registered, _preview_all),
    ]
    page_reasons.SOLUTIONS["stretched"] = [
        Solution("PDF에서 보이던 비율로", "원본 이미지 데이터는 그대로 두고, PDF로 내보낼 때 이 비율의 쪽으로 만듭니다. "
                 "이미지로 내보내면 원본 비율로 저장됩니다.", _as_pdf, _preview_image_area),
        Solution("원본 비율로", "원본 이미지를 그대로 꺼냅니다(PDF로 내보내도 원본 비율).", _as_original, _preview_original),
    ]

