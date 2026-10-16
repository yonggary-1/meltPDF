"""
썸네일 안쪽의 [?] 누르기 - PDF에서 쪽 그대로 넣은(파란 테두리) 타일의 오른쪽 위 [?]를 누르면 그 이유 창을 연다(v0.21.0, 사용자 요청).

[?]는 타일과 같은 캔버스 그림이다(tile_view - 자식 위젯을 두지 않는 원칙). 누름을 선택(selection.py)과 끌기(drag_reorder.py)보다
먼저 받아야 하므로 이 기능은 그것들보다 먼저 만들어야 한다(app_window). [?]를 누른 경우에만 뒤 처리를 막는다("break").
"""
from __future__ import annotations

from typing import Callable

from doc_model import DocModel
from tile_view import TileView


class PageReasonBadge:
    def __init__(self, view: TileView, model: DocModel, open_fn: Callable[[str], None]):
        self.view = view
        self.model = model
        self.open_fn = open_fn
        self._pressed = False
        c = view.canvas
        c.bind("<Button-1>", self._on_press, add="+")
        c.bind("<ButtonRelease-1>", self._on_release, add="+")

    def _on_press(self, event):
        c = self.view.canvas
        iid = self.view.badge_at(c.canvasx(event.x), c.canvasy(event.y))
        if iid is None:
            self._pressed = False
            return None
        self._pressed = True
        c.focus_set()
        self.model.select_only(iid)
        c.after_idle(lambda: self.open_fn(iid))
        return "break"

    def _on_release(self, _event):
        if self._pressed:                       # [?]를 누른 뒤 뗌: 끌기/두 번 누름 처리에 넘기지 않는다
            self._pressed = False
            return "break"
        return None
