"""
키보드 이동 - 목록(썸네일 영역)에서 방향키, Home/End, PageUp/PageDown으로 선택을 옮긴다.

- 방향키: 타일형은 좌우 1칸, 위아래 한 줄(열 수만큼). 목록형은 위아래 1줄(좌우 키는 무시).
- Home / End: 맨 처음 / 맨 끝.  PageUp / PageDown: 화면에 보이는 줄 수만큼 위/아래.
- 아무것도 선택 안 된 상태에서 누르면 첫 항목(End/PageUp은 마지막 항목)부터 시작한다.
- 이동하면 그 항목만 선택되고, 화면 밖이면 보이도록 스크롤한다.
선택 상태는 모델(doc_model)이 들고 있으므로 여기서는 model.select_only()만 부른다.
"""
from __future__ import annotations

from typing import Optional

from config import MARGIN, GRID_PITCH_Y, LIST_PITCH_Y
from doc_model import DocModel
from tile_view import TileView


class KeyNav:
    def __init__(self, view: TileView, model: DocModel):
        self.view = view
        self.model = model
        self.current: Optional[str] = None     # 키보드 이동의 기준 항목(마지막으로 누르거나 이동한 항목)
        c = view.canvas
        c.bind("<Button-1>", self._remember_click, add="+")
        c.bind("<Enter>", lambda e: c.focus_set(), add="+")   # 마우스를 올려 두면 바로 키보드가 먹는다
        for seq, key in (("<Up>", "up"), ("<Down>", "down"), ("<Left>", "left"), ("<Right>", "right"),
                         ("<Home>", "home"), ("<End>", "end"), ("<Prior>", "pageup"), ("<Next>", "pagedown")):
            c.bind(seq, lambda e, k=key: self._on_key(k))
        model.subscribe("structure", lambda: c.focus_set())   # 항목을 불러온 직후에도 바로 키를 받게 한다

    # ---------------------------------------------------------- 기준 항목
    def _remember_click(self, event):
        c = self.view.canvas
        iid = self.view.tile_at(c.canvasx(event.x), c.canvasy(event.y))
        if iid is not None:
            self.current = iid

    def _start_index(self) -> Optional[int]:
        order = self.model.order
        if self.current in order and self.current in self.model.selected:
            return order.index(self.current)
        picked = [i for i, iid in enumerate(order) if iid in self.model.selected]
        return picked[-1] if picked else None

    # ---------------------------------------------------------- 이동 계산
    def _page_rows(self) -> int:
        pitch = GRID_PITCH_Y if self.view.view_mode_var.get() == "grid" else LIST_PITCH_Y
        return max(1, self.view.canvas.winfo_height() // pitch)

    def _target(self, key: str, idx: Optional[int]) -> Optional[int]:
        n = len(self.model.order)
        grid = self.view.view_mode_var.get() == "grid"
        cols = self.view.cols() if grid else 1
        if idx is None:                                   # 아직 선택이 없으면 끝에서부터 시작
            return n - 1 if key in ("end", "pageup") else 0
        if key == "home":
            return 0
        if key == "end":
            return n - 1
        if key in ("left", "right"):
            if not grid:
                return idx
            return min(max(idx + (1 if key == "right" else -1), 0), n - 1)
        step = cols if key in ("up", "down") else cols * self._page_rows()
        if key in ("up", "pageup"):
            return idx - step if idx - step >= 0 else idx % cols   # 위로 넘치면 같은 열의 맨 윗줄
        t = idx + step                                    # 아래쪽
        if t < n:
            return t
        # 마지막 줄이 덜 찬 경우: 아래 칸이 없어도 아래 줄이 있으면 맨 끝 항목으로 간다
        return n - 1 if idx // cols < (n - 1) // cols else idx

    def _on_key(self, key: str):
        order = self.model.order
        if not order:
            return "break"
        idx = self._target(key, self._start_index())
        if idx is None:
            return "break"
        iid = order[idx]
        self.current = iid
        self.model.select_only(iid)
        self._scroll_to(idx)
        return "break"

    # ---------------------------------------------------------- 화면 밖이면 스크롤
    def _scroll_to(self, idx: int):
        v = self.view
        c = v.canvas
        _, y, _, h = v.tile_rect(idx)
        top = c.canvasy(0)
        bottom = top + c.winfo_height()
        total = max(v.content_height(), 1)
        if y - MARGIN < top:
            c.yview_moveto(max(y - MARGIN, 0) / total)
        elif y + h + MARGIN > bottom:
            c.yview_moveto((y + h + MARGIN - c.winfo_height()) / total)
