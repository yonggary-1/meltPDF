"""
타일 화면 - 썸네일 목록을 캔버스에 그리고, 스크롤/창 크기 변화/타일 위치 계산을 맡는다.
(선택은 selection.py, 드래그로 순서 바꾸기는 drag_reorder.py가 맡는다 - 여기엔 없다.)

타일은 "위젯"이 아니라 캔버스가 직접 그리는 그림(캔버스 아이템: 사각형+이미지+글자)이다.
Tk는 위젯 하나하나가 OS의 독립된 자식 창이라, 위젯끼리 겹쳐 움직이면 지나간 자리가 안
지워지는 검은 얼룩이 생기고 z-순서도 마음대로 안 된다. 캔버스 하나가 배경·타일·드래그
표시를 전부 자기 그림으로 그리면 그 문제들이 구조적으로 사라진다. 그래서 이 영역 안에는
자식 위젯이 하나도 없어야 한다(새 기능을 넣을 때도 이 원칙을 지킬 것).

모델의 알림을 받아 스스로 갱신한다:
  structure -> rebuild()  /  order -> reflow()  /  selection -> refresh_colors()

캔버스에는 보이는 곳과 위아래 한 화면 분량의 타일만 그려 두고, 스크롤하면 바꿔 그린다(v0.19.3). 목록이 수천 장이어도
화면 쪽 일은 그려 둔 수십 개만큼이다. 타일 위치는 번호로 계산하므로(tile_rect, tile_at) 그려 두지 않은 타일도 눌러/끌어 놓을 자리를 안다.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Dict, List, Optional

import pdf_core
from config import (
    BG_COVER, BG_DRAGGING, BG_NORMAL, DAMAGED_OUTLINE, DAMAGED_OUTLINE_W, BG_SELECTED, GRID_PITCH_X, GRID_PITCH_Y, LIST_PITCH_Y,
    LIST_TILE_H, MARGIN, THUMB_MAX, TILE_H, TILE_W,
)
from doc_model import DocModel

WINDOW_MARGIN = 1.0       # 보이는 곳 위아래로 이만큼(화면 높이 배수) 더 그려 둔다(스크롤이 매끄럽게)


class TileView:
    def __init__(self, parent: tk.Misc, model: DocModel):
        self.model = model
        # 캔버스에 그려 둔 타일(그릴 범위 안의 것만): iid -> {"idx": 자리, 역할: 캔버스 아이템 id}
        self.tile_items: Dict[str, Dict[str, int]] = {}
        self._drawn_key = None              # 지금 그려 둔 범위/배치(스크롤 때 바뀌었는지 보려고)
        self._sync_pending = False
        self._region = None                 # 마지막으로 설정한 스크롤 영역
        self.dragging_iid: Optional[str] = None   # 끌고 있는 타일(회색) - drag_reorder.py가 정한다
        self._last_cols: Optional[int] = None
        # 타일을 다시 그린 직후에 불려야 하는 함수들(예: 드래그 표시를 맨 위로 올리기).
        # 다른 기능이 여기 함수를 등록하기만 하면 되고, 이 파일은 그 기능을 몰라도 된다.
        self.layout_hooks: List[Callable[[], None]] = []

        self.view_mode_var = tk.StringVar(value="grid", master=parent)  # 'grid'(타일형) | 'list'(목록형)

        # 썸네일 영역: 스크롤 가능한 Canvas (트리뷰는 행 높이가 고정이라 세로로 긴 썸네일이 잘림)
        self.frame = ttk.Frame(parent)
        self.canvas = tk.Canvas(self.frame, highlightthickness=0, bg=BG_NORMAL, takefocus=1)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vsb = ttk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        # 스크롤바를 캔버스 "옆"(pack)이 아니라 캔버스 "위"에 겹쳐서 고정 배치한다. 캔버스가
        # 창 오른쪽 끝까지 차지해야 드래그 중 표시(유령 썸네일)도 끝까지 갈 수 있다.
        # 스크롤바는 한 번 놓은 뒤 움직이지 않으므로 "움직이는 위젯의 잔상" 문제와 무관하다.
        self.vsb.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):   # Windows/macOS, Linux 위/아래
            self.canvas.bind(seq, self._on_mousewheel)

        model.subscribe("structure", self.rebuild)
        model.subscribe("order", self.reflow)
        model.subscribe("selection", self.refresh_colors)

    # ---------------------------------------------------------- 배치 계산
    def layout_width(self) -> int:
        """타일을 배치할 때 쓸 실제 가용 폭. 스크롤바가 캔버스 위에 겹쳐 있으므로,
        타일이 스크롤바 밑에 깔리지 않도록 스크롤바 폭과 좌우 여백을 뺀다."""
        w = self.canvas.winfo_width()
        if not w or w <= 1:
            return GRID_PITCH_X
        try:
            sb = self.vsb.winfo_reqwidth() or 16
        except tk.TclError:
            sb = 16
        return max(GRID_PITCH_X, w - sb - MARGIN)

    def cols(self) -> int:
        return max(1, self.layout_width() // GRID_PITCH_X)

    def content_height(self) -> int:
        n = len(self.model.order)
        if n == 0:
            return 0
        if self.view_mode_var.get() == "grid":
            rows = (n + self.cols() - 1) // self.cols()
            return MARGIN * 2 + rows * GRID_PITCH_Y
        return MARGIN * 2 + n * LIST_PITCH_Y

    def update_scrollregion(self):
        """스크롤 영역은 타일 내용만 기준으로 직접 계산한다. bbox("all")을 쓰면 드래그 중에만
        잠깐 존재하는 유령/삽입 막대까지 포함되어 스크롤 범위가 멋대로 늘었다 줄었다 한다."""
        region = (0, 0, self.layout_width(), max(self.content_height(), 1))
        if region != self._region:          # 같은 값으로 다시 설정하면 스크롤 알림 -> 다시 그리기가 되풀이된다
            self._region = region
            self.canvas.configure(scrollregion=region)

    def tile_rect(self, idx: int) -> tuple:
        """idx번째 자리의 (x, y, 폭, 높이). 위젯 크기를 재지 않고 코드가 직접 계산하므로
        드래그 중이든 아니든 항상 정확하다."""
        if self.view_mode_var.get() == "grid":
            r, c = divmod(idx, self.cols())
            return (MARGIN + c * GRID_PITCH_X, MARGIN + r * GRID_PITCH_Y, TILE_W, TILE_H)
        w = max(TILE_W, self.layout_width() - MARGIN * 2)
        return (MARGIN, MARGIN + idx * LIST_PITCH_Y, w, LIST_TILE_H)

    def tile_at(self, cx: float, cy: float) -> Optional[str]:
        """캔버스 좌표에 있는 타일의 id. 빈 자리를 누르면 None."""
        order = self.model.order
        if not order:
            return None
        if self.view_mode_var.get() == "grid":
            cols = self.cols()
            col = int((cx - MARGIN) // GRID_PITCH_X)
            row = int((cy - MARGIN) // GRID_PITCH_Y)
            if col < 0 or col >= cols or row < 0:
                return None
            idx = row * cols + col
        else:
            idx = int((cy - MARGIN) // LIST_PITCH_Y)
        if idx < 0 or idx >= len(order):
            return None
        x, y, w, h = self.tile_rect(idx)
        if not (x <= cx <= x + w and y <= cy <= y + h):
            return None   # 칸 사이 여백을 누른 경우
        return order[idx]

    # ---------------------------------------------------------- 스크롤 / 창 크기
    def _on_yscroll(self, first, last):
        self.vsb.set(first, last)
        self._schedule_sync()          # 스크롤하면 그릴 범위가 바뀐다

    def _on_canvas_resize(self, event):
        cols = self.cols()
        if self.view_mode_var.get() == "grid":
            if cols != self._last_cols:
                self._last_cols = cols
                self.reflow()
            else:
                self._schedule_sync()  # 높이만 바뀌면 그릴 범위만 다시 본다
        else:
            self.reflow()  # 목록형은 줄 폭이 창 폭을 따라가므로 폭이 바뀌면 다시 그린다

    def on_view_mode_change(self):
        self._last_cols = None
        self.rebuild()
        self.canvas.yview_moveto(0)

    def _on_mousewheel(self, event):
        num = getattr(event, "num", None)
        if num == 4:
            self.canvas.yview_scroll(-3, "units")
        elif num == 5:
            self.canvas.yview_scroll(3, "units")
        else:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    # ---------------------------------------------------------- 그릴 범위
    def window_range(self) -> range:
        """캔버스에 실제로 그려 둘 타일 번호 범위: 보이는 곳 + 위아래 WINDOW_MARGIN 화면."""
        c = self.canvas
        n = len(self.model.order)
        h = max(c.winfo_height(), 1)
        top = c.canvasy(0) - h * WINDOW_MARGIN
        bottom = c.canvasy(h) + h * WINDOW_MARGIN
        if self.view_mode_var.get() == "grid":
            cols = self.cols()
            r0 = max(int((top - MARGIN) // GRID_PITCH_Y), 0)
            r1 = max(int((bottom - MARGIN) // GRID_PITCH_Y) + 1, 0)
            return range(min(r0 * cols, n), min(r1 * cols, n))
        i0 = max(int((top - MARGIN) // LIST_PITCH_Y), 0)
        i1 = max(int((bottom - MARGIN) // LIST_PITCH_Y) + 1, 0)
        return range(min(i0, n), min(i1, n))

    def _schedule_sync(self):
        if self._sync_pending:
            return
        self._sync_pending = True
        try:
            self.canvas.after_idle(self._sync_idle)
        except tk.TclError:
            self._sync_pending = False

    def _sync_idle(self):
        self._sync_pending = False
        self._sync(force=False)

    # ---------------------------------------------------------- 타일 그리기
    def _tile_bg(self, iid: str) -> str:
        if iid == self.dragging_iid:
            return BG_DRAGGING
        if iid == self.model.cover_id:
            return BG_COVER
        if iid in self.model.selected:
            return BG_SELECTED
        return BG_NORMAL

    @staticmethod
    def _short_name(name: str, maxlen: int = 20) -> str:
        return name if len(name) <= maxlen else name[: maxlen - 1] + "…"

    @staticmethod
    def _size_label(item: pdf_core.PageItem) -> str:
        # kind='image': 실제 픽셀 크기. kind='pdf_page': 원본 페이지 크기(pt, 72pt=1inch) -
        # 이 페이지는 원본 그대로 복사되므로 "px" 표기로 오해하지 않도록 단위를 구분해서 표시.
        if item.kind == "image":
            return f"{item.width}x{item.height}px"
        return f"{item.width}x{item.height}pt (원본 그대로)"

    def rebuild(self):
        """목록 내용이 바뀜(추가/삭제, 표지, 이름, 보기 모드) -> 그릴 범위의 타일을 새로 그린다.
        그려 둔 범위보다 뒤에 항목만 들어왔으면(보통의 불러오기) 그려 둔 타일은 그대로 두고 스크롤 영역만 늘린다."""
        added, at = self.model.added_ids, self.model.added_at
        if added is not None and at is not None and self._drawn_key is not None and at >= self._drawn_key[1]:
            self._sync(force=False)
            return
        self._sync(force=True)

    def reflow(self, start: int = 0):
        """순서나 창 크기가 바뀜 -> 그릴 범위의 타일을 새 자리에 다시 그린다(start는 예전 호환용, 쓰지 않음)."""
        self._sync(force=True)

    def _sync(self, force: bool):
        """캔버스에는 그릴 범위(보이는 곳 + 위아래 한 화면)의 타일만 둔다(v0.19.3).

        예전에는 모든 항목의 타일(테두리, 썸네일, 글자)을 캔버스에 두고, 항목이 들어올 때마다 뒤쪽 타일 수천 개를 옮겼다.
        목록이 수천 장이 되면 묶음 하나 넣는 데 화면 스레드가 0.1초 넘게 걸려, 불러오기 스레드가 화면 스레드를 기다리느라
        거의 멈춘 것처럼 느려졌다(CPU와 메모리는 남아 있는데 느림 - 화면 스레드 하나만 바빴음).
        이제 무엇을 바꾸든 화면에 그려 둔 수십 개만 다시 그리므로 목록 장수와 상관없이 걸리는 시간이 같다.
        force=False(스크롤)일 때는 범위가 그대로면 아무것도 하지 않고, 범위를 벗어난 타일만 지우고 새로 들어온 타일만 그린다."""
        self.update_scrollregion()
        order = self.model.order
        rng = self.window_range()
        key = (rng.start, rng.stop, len(order), self.view_mode_var.get(), self.cols(), self.layout_width())
        if not force and key == self._drawn_key:
            return
        want = {order[i]: i for i in rng}
        old = set(self.tile_items)
        c = self.canvas
        if force:
            c.delete("tile")
            self.tile_items = {}
        else:
            for iid in [k for k, it in self.tile_items.items() if want.get(k) != it["idx"]]:
                ids = [v for k2, v in self.tile_items.pop(iid).items() if k2 != "idx" and v is not None]
                if ids:
                    c.delete(*ids)
        for iid, idx in want.items():
            if iid not in self.tile_items:
                self._draw_tile(iid, idx)
        for iid in old - set(want):
            self.model.release_photo(iid)        # 화면 그림(윈도우 그래픽 자원)은 그려 둔 타일 것만 들고 있는다
        self._drawn_key = key
        self._run_hooks()

    def img_pos(self, idx: int) -> tuple:
        """idx번째 타일에서 썸네일 그림의 가운데 좌표."""
        x, y, w, h = self.tile_rect(idx)
        if self.view_mode_var.get() == "grid":
            return (x + w / 2, y + 4 + (THUMB_MAX + 8) / 2)
        return (x + 6 + (THUMB_MAX + 8) / 2, y + h / 2)

    def _draw_tile(self, iid: str, idx: int):
        item = self.model.items[iid]
        photo = self.model.photo(iid)
        bg = self._tile_bg(iid)
        cover_mark = "★ " if iid == self.model.cover_id else ""
        x, y, w, h = self.tile_rect(idx)
        tag = ("tile", f"tile:{iid}")
        c = self.canvas
        damaged = getattr(item, "damaged", False)        # 손상된 이미지: 빨간 굵은 테두리
        items = {"idx": idx,
                 "rect": c.create_rectangle(x, y, x + w, y + h, fill=bg,
                                            outline=DAMAGED_OUTLINE if damaged else "#9a9a9a",
                                            width=DAMAGED_OUTLINE_W if damaged else 1, tags=tag)}
        items["img"] = c.create_image(*self.img_pos(idx), image=photo, tags=tag) if photo is not None else None
        if self.view_mode_var.get() == "grid":
            items["text"] = c.create_text(
                x + w / 2, y + THUMB_MAX + 14, anchor="n", justify="center",
                text=self._short_name(cover_mark + item.label, 22),
                font=("", 9), width=w - 8, tags=tag,
            )
        else:
            kind_label = ("이미지" if item.kind == "image"
                          else f"PDF({Path(item.origin_pdf).name} p{item.origin_page_no})")
            tx = x + THUMB_MAX + 24
            # 캔버스 글자는 width를 주면 그 폭에서 알아서 줄바꿈된다 - 창을 좁혀도 긴 파일명이 안 잘린다.
            wrap = max(60, w - (THUMB_MAX + 34))
            items["text"] = c.create_text(tx, y + h / 2 - 10, anchor="w", justify="left",
                                          text=f"{cover_mark}{item.label}",
                                          font=("", 10, "bold"), width=wrap, tags=tag)
            items["meta"] = c.create_text(tx, y + h / 2 + 12, anchor="w", justify="left",
                                          text=f"{self._size_label(item)}   |   {kind_label}" + ("   |   손상됨(일부만 표시)" if damaged else ""),
                                          fill="#555555", width=wrap, tags=tag)
        self.tile_items[iid] = items

    def refresh_colors(self):
        for iid, items in self.tile_items.items():
            try:
                self.canvas.itemconfigure(items["rect"], fill=self._tile_bg(iid))
            except tk.TclError:
                pass

    def _run_hooks(self):
        for fn in self.layout_hooks:
            fn()
