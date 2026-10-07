"""
선택 - 타일을 클릭하면 선택, Ctrl+클릭은 선택 토글, 빈 곳을 클릭하면 선택 해제.
선택 상태 자체는 모델(doc_model)이 들고 있고, 여기는 "마우스 클릭 -> 모델 변경"만 한다.
(누른 채로 끌어서 순서를 바꾸는 동작은 drag_reorder.py에 있다.)
"""
from __future__ import annotations

from doc_model import DocModel
from tile_view import TileView

CTRL_MASK = 0x0004


class Selection:
    def __init__(self, view: TileView, model: DocModel):
        self.view = view
        self.model = model
        view.canvas.bind("<Button-1>", self._on_press, add="+")

    def _on_press(self, event):
        canvas = self.view.canvas
        canvas.focus_set()
        iid = self.view.tile_at(canvas.canvasx(event.x), canvas.canvasy(event.y))
        ctrl = bool(event.state & CTRL_MASK)
        if iid is None:
            if not ctrl:
                self.model.clear_selection()
        elif ctrl:
            self.model.toggle_select(iid)
        else:
            self.model.select_only(iid)
