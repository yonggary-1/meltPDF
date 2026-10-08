"""
이미지 보기 창 - 썸네일을 두 번 누르거나(또는 선택하고 Enter) 원본 크기의 이미지를 팝업 창으로 보여준다.

창 아래에 세 버튼: [-] 축소, [=] 창에 맞춤, [+] 확대. (마우스 휠은 가리킨 곳을 기준으로 확대/축소, Esc는 닫기)
이미지가 창보다 크게 확대된 상태에서는 마우스로 끌어서 옮겨 볼 수 있다.
- 화면에 보이는 부분만 잘라서 크기를 바꿔 그리므로, 아주 큰 이미지를 크게 확대해도 메모리/속도 문제가 없다.
- 기존 PDF의 페이지는 원본 페이지를 큼직하게 그려서 보여준다(보기 전용 - 내보내기에는 영향 없음).
- 이 기능은 목록(모델)을 바꾸지 않는다. 선택/드래그 동작과 겹치지 않도록 "눌렀다 뗀" 시점만 본다.
"""
from __future__ import annotations

import io
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image, ImageTk

import damaged_image
import pdf_core
from config import APP_TITLE
from doc_model import DocModel
from tile_view import TileView

_DOUBLE_CLICK_S = 0.45          # 두 번 누름으로 인정하는 시간 간격
_CLICK_SLOP_PX = 6              # 누른 자리와 뗀 자리가 이 정도 이내여야 "클릭"(끌기가 아님)
_ZOOM_STEP = 1.25
_MIN_SCALE, _MAX_SCALE = 0.02, 32.0
_PDF_PAGE_LONG_SIDE_PX = 2600   # 기존 PDF 페이지를 그릴 때 긴 변의 크기(보기 전용)


def load_full_image(item: pdf_core.PageItem) -> Image.Image:
    """목록 항목의 원본 이미지를 PIL로 연다(썸네일이 아니라 실제 크기)."""
    if item.kind == "pdf_page":
        doc = fitz.open(item.origin_pdf)
        try:
            page = doc[item.origin_page_no - 1]
            z = min(4.0, _PDF_PAGE_LONG_SIDE_PX / max(page.rect.width, page.rect.height, 1))
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            doc.close()
    data = item.raster_bytes
    path = item.source_path if data is None else None
    try:
        with Image.open(io.BytesIO(data) if data is not None else path) as im:
            im.load()
            return im.copy()
    except Exception:
        return damaged_image.open_tolerant(data=data, path=path)     # 깨진 이미지도 읽히는 부분까지 보여준다


def _to_display(im: Image.Image) -> Image.Image:
    """화면에 그릴 수 있는 RGB로 바꾼다(투명한 부분은 흰색)."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return im.convert("RGB")


class ImageViewer:
    def __init__(self, root: tk.Misc, model: DocModel, view: TileView):
        self.root = root
        self.model = model
        self.view = view
        self._press = None                   # (캔버스 x, y) 마지막으로 누른 자리
        self._last_click = (0.0, None)       # (시각, 항목 id) - 두 번 누름 판단용
        view.canvas.bind("<Button-1>", self._on_press, add="+")
        view.canvas.bind("<ButtonRelease-1>", self._on_release, add="+")
        view.canvas.bind("<Return>", lambda e: self.open_selected(), add="+")
        self.win: Optional[tk.Toplevel] = None
        self.canvas: Optional[tk.Canvas] = None
        self.zoom_label: Optional[ttk.Label] = None
        self.img: Optional[Image.Image] = None
        self._photo = None
        self.scale = 1.0
        self.cx = self.cy = 0.0              # 캔버스 한가운데에 보이는 이미지 위의 점
        self.fit_mode = True
        self._drag_from = None

    # ------------------------------------------------------------ 열기 (두 번 누름 / Enter)
    def _on_press(self, event):
        c = self.view.canvas
        self._press = (c.canvasx(event.x), c.canvasy(event.y))

    def _on_release(self, event):
        c = self.view.canvas
        x, y = c.canvasx(event.x), c.canvasy(event.y)
        if self._press is None or abs(x - self._press[0]) > _CLICK_SLOP_PX or abs(y - self._press[1]) > _CLICK_SLOP_PX:
            self._last_click = (0.0, None)   # 끌기였다
            return
        iid = self.view.tile_at(x, y)
        now = time.monotonic()
        last_t, last_iid = self._last_click
        if iid is not None and iid == last_iid and now - last_t <= _DOUBLE_CLICK_S:
            self._last_click = (0.0, None)
            self.open_item(iid)
        else:
            self._last_click = (now, iid)

    def open_selected(self):
        for iid in self.model.order:
            if iid in self.model.selected:
                self.open_item(iid)
                return

    def open_item(self, iid: str):
        item = self.model.items.get(iid)
        if item is None:
            return
        try:
            im = _to_display(load_full_image(item))
        except Exception as e:
            messagebox.showwarning(APP_TITLE, f"이미지를 열 수 없습니다: {item.label}\n({e})")
            return
        self._ensure_window()
        self.img = im
        self.fit_mode = True
        self.cx, self.cy = im.width / 2, im.height / 2
        title = item.label + ("  - 손상됨(읽을 수 있는 부분만 표시)" if getattr(item, "damaged", False) else "")
        self.win.title(title)
        self._size_window_for(im)
        self.win.lift()
        self.win.focus_force()
        self.canvas.focus_set()
        self.win.update_idletasks()
        self._fit()

    # ------------------------------------------------------------ 창 만들기
    def _ensure_window(self):
        if self.win is not None and self.win.winfo_exists():
            return
        win = self.win = tk.Toplevel(self.root)
        win.minsize(360, 300)
        win.transient(self.root)
        canvas = self.canvas = tk.Canvas(win, bg="#2b2b2b", highlightthickness=0, takefocus=1)
        canvas.pack(side="top", fill="both", expand=True)
        bar = ttk.Frame(win)
        bar.pack(side="bottom", fill="x", pady=4)
        inner = ttk.Frame(bar)
        inner.pack()
        style = ttk.Style(win)
        style.configure("Viewer.TButton", font=("", 14, "bold"), padding=(10, 2))
        for text, cmd in (("-", self.zoom_out), ("=", self._fit), ("+", self.zoom_in)):
            ttk.Button(inner, text=text, width=3, style="Viewer.TButton", command=cmd, takefocus=0).pack(side="left", padx=4)
        self.zoom_label = ttk.Label(inner, text="", width=8, anchor="w")
        self.zoom_label.pack(side="left", padx=(10, 0))
        canvas.bind("<Configure>", lambda e: self._on_resize())
        canvas.bind("<ButtonPress-1>", self._drag_start)
        canvas.bind("<B1-Motion>", self._drag_move)
        canvas.bind("<ButtonRelease-1>", lambda e: self._set_cursor())
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(seq, self._on_wheel)
        for seq, fn in (("<plus>", self.zoom_in), ("<KP_Add>", self.zoom_in), ("<minus>", self.zoom_out),
                        ("<KP_Subtract>", self.zoom_out), ("<equal>", self._fit)):
            win.bind(seq, lambda e, fn=fn: fn())
        win.bind("<Escape>", lambda e: self.close())
        win.protocol("WM_DELETE_WINDOW", self.close)

    def _size_window_for(self, im: Image.Image):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        max_w, max_h = int(sw * 0.8), int(sh * 0.8) - 50
        s = min(max_w / im.width, max_h / im.height, 1.0)
        w = max(480, int(im.width * s))
        h = max(360, int(im.height * s)) + 50
        x = max(0, self.root.winfo_rootx() + 40)
        y = max(0, self.root.winfo_rooty() + 40)
        self.win.geometry(f"{w}x{h}+{min(x, max(0, sw - w))}+{min(y, max(0, sh - h - 40))}")

    def close(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = self.canvas = self.img = self._photo = None

    # ------------------------------------------------------------ 확대/축소/맞춤
    def _canvas_size(self):
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def _fit(self):
        if self.img is None:
            return
        w, h = self._canvas_size()
        self.scale = max(_MIN_SCALE, min(_MAX_SCALE, min(w / self.img.width, h / self.img.height)))
        self.cx, self.cy = self.img.width / 2, self.img.height / 2
        self.fit_mode = True
        self._render()

    def _zoom_to(self, new_scale: float, ax: Optional[float] = None, ay: Optional[float] = None):
        """new_scale로 바꾼다. (ax, ay) 캔버스 위의 점이 가리키던 이미지 위의 점은 그대로 둔다(없으면 창 한가운데)."""
        if self.img is None:
            return
        w, h = self._canvas_size()
        ax = w / 2 if ax is None else ax
        ay = h / 2 if ay is None else ay
        px = self.cx - w / (2 * self.scale) + ax / self.scale      # 그 점이 가리키는 이미지 위의 좌표
        py = self.cy - h / (2 * self.scale) + ay / self.scale
        self.scale = max(_MIN_SCALE, min(_MAX_SCALE, new_scale))
        self.cx = px - ax / self.scale + w / (2 * self.scale)
        self.cy = py - ay / self.scale + h / (2 * self.scale)
        self.fit_mode = False
        self._render()

    def zoom_in(self):
        self._zoom_to(self.scale * _ZOOM_STEP)

    def zoom_out(self):
        self._zoom_to(self.scale / _ZOOM_STEP)

    def _on_wheel(self, event):
        up = event.num == 4 or getattr(event, "delta", 0) > 0
        self._zoom_to(self.scale * (_ZOOM_STEP if up else 1 / _ZOOM_STEP), event.x, event.y)

    def _on_resize(self):
        if self.img is None:
            return
        if self.fit_mode:
            self._fit()
        else:
            self._render()

    # ------------------------------------------------------------ 끌어서 옮기기
    def _can_pan(self) -> bool:
        w, h = self._canvas_size()
        return self.img is not None and (self.img.width * self.scale > w + 0.5 or self.img.height * self.scale > h + 0.5)

    def _set_cursor(self):
        if self.canvas is not None:
            self.canvas.configure(cursor="fleur" if self._can_pan() else "")

    def _drag_start(self, event):
        self._drag_from = (event.x, event.y) if self._can_pan() else None
        self.canvas.focus_set()

    def _drag_move(self, event):
        if self._drag_from is None:
            return
        dx, dy = event.x - self._drag_from[0], event.y - self._drag_from[1]
        self._drag_from = (event.x, event.y)
        self.cx -= dx / self.scale
        self.cy -= dy / self.scale
        self.fit_mode = False
        self._render()

    # ------------------------------------------------------------ 그리기 (보이는 부분만)
    def _clamp_center(self, w: int, h: int):
        iw, ih = self.img.width, self.img.height
        half_w, half_h = w / (2 * self.scale), h / (2 * self.scale)
        self.cx = iw / 2 if iw <= 2 * half_w else min(max(self.cx, half_w), iw - half_w)
        self.cy = ih / 2 if ih <= 2 * half_h else min(max(self.cy, half_h), ih - half_h)

    def _render(self):
        if self.img is None or self.canvas is None:
            return
        w, h = self._canvas_size()
        self._clamp_center(w, h)
        s = self.scale
        iw, ih = self.img.width, self.img.height
        left, top = self.cx - w / (2 * s), self.cy - h / (2 * s)
        sl, st = max(0.0, left), max(0.0, top)                  # 이미지 안에 있는 부분
        sr, sb = min(float(iw), left + w / s), min(float(ih), top + h / s)
        self.canvas.delete("img")
        if sr > sl and sb > st:
            dw, dh = max(1, round((sr - sl) * s)), max(1, round((sb - st) * s))
            resample = Image.NEAREST if s >= 8 else (Image.LANCZOS if s < 1 else Image.BICUBIC)
            piece = self.img.resize((dw, dh), resample=resample, box=(sl, st, sr, sb))
            self._photo = ImageTk.PhotoImage(piece)
            self.canvas.create_image(round((sl - left) * s), round((st - top) * s), anchor="nw",
                                     image=self._photo, tags="img")
        self.zoom_label.configure(text=f"{round(s * 100)}%")
        self._set_cursor()
