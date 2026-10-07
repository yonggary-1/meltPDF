"""
드래그로 순서 바꾸기 - 썸네일을 누른 채로 끌어서 원하는 자리에 놓으면 순서가 바뀐다.

동작 방식:
- 드래그하는 동안에는 실제 순서도, 다른 타일도 전혀 움직이지 않는다. 잡은 타일은 제자리에서
  회색이 되고, "놓으면 여기로 간다"를 파란 삽입 막대로 보여주고, 유령 썸네일이 커서를 따라간다.
- 마우스를 놓는 순간에만 모델의 순서를 바꾼다(모델이 알림을 보내 타일 화면이 위치를 다시 잡는다).
- 유령/삽입 막대는 타일과 같은 캔버스가 그리는 캔버스 아이템이라 tag_raise로 항상 타일 위에
  보이고, 겹친 위젯의 다시 그리기 경합(검은 얼룩)이 없다.
- 유령 썸네일은 옵션(ghost_var)으로 끌 수 있다. 꺼도 삽입 막대는 나온다.
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

from config import (
    BG_DRAGGING, DRAG_THRESHOLD, DROP_MARK, DROP_MARK_W, GRID_GAP, GRID_PITCH_X,
    GRID_PITCH_Y, LIST_GAP, LIST_PITCH_Y, LIST_TILE_H, MARGIN, TILE_H, TILE_W,
)
from doc_model import DocModel
from tile_view import TileView


class DragReorder:
    def __init__(self, root: tk.Misc, view: TileView, model: DocModel):
        self.view = view
        self.model = model
        self.canvas = view.canvas
        self._drag: dict = {}
        # 드래그할 때 커서를 따라다니는 썸네일을 띄울지 여부(툴바 체크박스와 연결).
        self.ghost_var = tk.BooleanVar(value=True, master=root)

        self.canvas.bind("<Button-1>", self._on_press, add="+")
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        view.layout_hooks.append(self._raise_drag_items)

    # ---------------------------------------------------------- 마우스 이벤트
    def _xy(self, event) -> tuple:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _on_press(self, event):
        cx, cy = self._xy(event)
        iid = self.view.tile_at(cx, cy)
        if iid is None:
            self._drag = {}
            return
        self._drag = {
            "iid": iid, "start_x": cx, "start_y": cy,
            "dragging": False, "last_idx": None, "ghost": None, "mark": None,
        }

    def _on_motion(self, event):
        d = self._drag
        if not d or not d.get("iid"):
            return
        cx, cy = self._xy(event)
        if not d["dragging"]:
            if (abs(cx - d["start_x"]) <= DRAG_THRESHOLD
                    and abs(cy - d["start_y"]) <= DRAG_THRESHOLD):
                return
            d["dragging"] = True
            self._start_drag_visual(d["iid"])
        self._move_ghost(cx, cy)
        b = self._drop_boundary(cx, cy)
        d["last_idx"] = self._boundary_to_index(b, d["iid"])
        self._draw_drop_mark(b, cy)

    def _on_release(self, event):
        d = self._drag
        if not d or not d.get("iid"):
            return
        iid, was_dragging, idx = d["iid"], d.get("dragging"), d.get("last_idx")
        self._clear_drag_items()
        self._drag = {}
        if was_dragging:
            if idx is not None:
                self.model.move_to_index(iid, idx)
            self.view.refresh_colors()

    # ---------------------------------------------------------- 드래그 표시
    def _start_drag_visual(self, iid: str):
        """드래그 시작 - 잡은 타일은 회색으로 바꾸고, 커서를 따라다닐 유령 썸네일을 만든다."""
        items = self.view.tile_items.get(iid)
        if items:
            self.canvas.itemconfigure(items["rect"], fill=BG_DRAGGING)
        if not self.ghost_var.get():
            return
        photo = self.model.photo_cache.get(iid)
        if photo is None:
            return
        try:
            self._drag["ghost"] = self.canvas.create_image(
                self._drag["start_x"], self._drag["start_y"], image=photo, tags=("dragitem",)
            )
            self.canvas.tag_raise(self._drag["ghost"])
        except tk.TclError:
            self._drag["ghost"] = None

    def _move_ghost(self, cx: float, cy: float):
        ghost = self._drag.get("ghost")
        if ghost is None:
            return
        try:
            self.canvas.coords(ghost, cx, cy)
        except tk.TclError:
            pass

    def _draw_drop_mark(self, boundary: int, cy: Optional[float] = None):
        """"놓으면 여기로 간다"를 보여주는 파란 삽입 막대. boundary는 _drop_boundary가 돌려준
        "경계선 번호"이고, 막대는 화면상 boundary번째 타일의 앞(왼쪽/위쪽) 경계에 그려진다.
        (잡은 타일 자신의 왼쪽/오른쪽 경계도 그대로 그려진다 - 놓아도 순서는 안 바뀐다.)"""
        coords = self._mark_coords(boundary, cy)
        if coords is None:
            return
        mark = self._drag.get("mark")
        try:
            if mark is None:
                mark = self.canvas.create_rectangle(*coords, fill=DROP_MARK,
                                                    outline=DROP_MARK, tags=("dragitem",))
                self._drag["mark"] = mark
                self._drag["mark_coords"] = coords
            elif coords != self._drag.get("mark_coords"):
                self.canvas.coords(mark, *coords)
                self._drag["mark_coords"] = coords
            self._raise_drag_items()
        except tk.TclError:
            pass

    def _mark_coords(self, boundary: int, cy: Optional[float]) -> Optional[tuple]:
        half = DROP_MARK_W / 2
        if self.view.view_mode_var.get() == "grid":
            cols = self.view.cols()
            r, c = divmod(boundary, cols)
            # 줄이 바뀌는 경계(=윗줄의 오른쪽 끝 = 아랫줄의 맨 앞)는 같은 자리다. 커서가 윗줄에
            # 있거나 목록의 맨 끝이면 윗줄 오른쪽 끝에 그려서 커서 옆에 막대가 보이게 한다.
            if c == 0 and boundary > 0:
                at_end = boundary >= len(self.model.order)
                cursor_row = max(0, int((cy - MARGIN) // GRID_PITCH_Y)) if cy is not None else r
                if at_end or cursor_row <= r - 1:
                    r, c = r - 1, cols
            x = max(MARGIN + c * GRID_PITCH_X - GRID_GAP / 2, half)   # 맨 왼쪽 경계가 잘리지 않게
            y = MARGIN + r * GRID_PITCH_Y
            return (x - half, y, x + half, y + TILE_H)
        y = max(MARGIN + boundary * LIST_PITCH_Y - LIST_GAP / 2, half)
        return (MARGIN, y - half,
                MARGIN + max(TILE_W, self.view.layout_width() - MARGIN * 2), y + half)

    def _raise_drag_items(self):
        """유령 썸네일과 삽입 막대를 항상 타일 위로 올린다(타일을 다시 그린 뒤에도 호출됨)."""
        for key in ("mark", "ghost"):
            item = self._drag.get(key) if self._drag else None
            if item is not None:
                try:
                    self.canvas.tag_raise(item)
                except tk.TclError:
                    pass

    def _clear_drag_items(self):
        for key in ("ghost", "mark"):
            item = self._drag.get(key)
            if item is not None:
                try:
                    self.canvas.delete(item)
                except tk.TclError:
                    pass
            self._drag[key] = None

    def _drop_boundary(self, cx: float, cy: float) -> int:
        """커서가 가리키는 "타일 사이 경계선"의 번호(0 ~ 전체 개수).
        boundary=k 는 화면상 k번째 타일의 앞 경계다. 커서가 있는 타일의 왼쪽(위쪽) 절반이면 그
        타일 앞 경계, 오른쪽(아래쪽) 절반이면 그 타일 뒤 경계로 잡는다. 잡은 타일 자신도 똑같이
        취급하므로 자기 왼쪽/오른쪽 경계에도 막대가 나온다. 좌표를 직접 계산하므로(가까운 타일
        찾기가 아니라) 맨 끝 경계에도 항상 도달할 수 있고, 타일 크기는 상수라 항상 정확하다."""
        total = len(self.model.order)
        if self.view.view_mode_var.get() == "grid":
            cols = self.view.cols()
            col = min(max(int((cx - MARGIN) // GRID_PITCH_X), 0), cols - 1)
            row = max(int((cy - MARGIN) // GRID_PITCH_Y), 0)
            right_half = (cx - MARGIN) - col * GRID_PITCH_X >= TILE_W / 2
            b = row * cols + col + (1 if right_half else 0)
        else:
            row = max(int((cy - MARGIN) // LIST_PITCH_Y), 0)
            lower_half = (cy - MARGIN) - row * LIST_PITCH_Y >= LIST_TILE_H / 2
            b = row + (1 if lower_half else 0)
        return min(b, total)

    def _boundary_to_index(self, boundary: int, dragged_iid: str) -> int:
        """경계선 번호 -> "잡은 타일을 뺀 순서"에서의 삽입 위치. 잡은 타일 자신의 앞/뒤 경계는
        둘 다 원래 자리(순서 변화 없음)가 된다."""
        order = self.model.order
        n = len(order) - (1 if dragged_iid in order else 0)
        try:
            p = order.index(dragged_iid)
        except ValueError:
            return min(boundary, n)
        return min(boundary if boundary <= p else boundary - 1, n)

    def _drop_index(self, cx: float, cy: float, exclude: Optional[str] = None) -> int:
        """커서 위치 -> "exclude를 뺀 순서"에서의 삽입 위치 (경계 계산의 편의 함수)."""
        return self._boundary_to_index(self._drop_boundary(cx, cy), exclude)
