"""
밖에서 끌어온 파일을 목록 중간에 놓기 - 목록에 이미지가 있을 때 탐색기 등에서 이미지/폴더/문서 파일을 끌어와
썸네일 영역 위에 올리면, 썸네일을 끌 때처럼 "놓으면 여기로 들어간다"를 파란 삽입 막대로 보여 주고,
놓으면 그 자리에 넣는다(여러 파일, 폴더, 압축/책 파일도 놓은 순서 그대로 그 자리에 이어진다).

- 끌어다 놓기 라이브러리(tkinterdnd2)의 <<DropEnter>>/<<DropPosition>>/<<DropLeave>>로 커서 위치를 받는다.
- 막대 위치 계산은 썸네일 끌기와 같은 함수를 쓴다(drop_slot.py).
- 놓을 때 file_loader가 anchor_for(event)를 불러 "그 자리 뒤쪽 항목 id"를 받아 간다. 새 항목은 그 항목 앞에 들어간다
  (불러오는 중에 그 항목을 지우면 목록 끝에 들어간다). 맨 끝 경계나 목록이 비어 있으면 None(끝에 붙임).
- 썸네일 영역이 아닌 곳(툴바 등)에 놓으면 예전처럼 목록 끝에 붙는다.
- 커서가 썸네일 영역의 위/아래 끝 가까이에 있으면 그쪽으로 조금씩 스크롤한다(화면 밖 자리에도 놓을 수 있게).
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

import activity_log
import drop_slot
from config import DROP_MARK, HAS_DND

TAG = "filedropmark"
EDGE = 28              # 위/아래 끝에서 이 픽셀 안이면 스크롤


class FileDropMark:
    def __init__(self, view, model, loader):
        self.view = view
        self.model = model
        self.canvas = view.canvas
        self._mark = None
        self._boundary: Optional[int] = None
        self._inside = False          # 활동 기록용: 끌어온 커서가 썸네일 영역 안에 있는가
        loader.drop_anchor = self.anchor_for
        view.layout_hooks.append(self._raise)
        if HAS_DND:
            self.canvas.dnd_bind("<<DropEnter>>", self._on_position, add="+")
            self.canvas.dnd_bind("<<DropPosition>>", self._on_position, add="+")
            self.canvas.dnd_bind("<<DropLeave>>", self._on_leave, add="+")

    # ---------------------------------------------------------- 끌어오는 동안
    def _canvas_xy(self, event) -> tuple:
        x = int(event.x_root) - self.canvas.winfo_rootx()
        y = int(event.y_root) - self.canvas.winfo_rooty()
        return x, y

    def _on_position(self, event):
        action = getattr(event, "action", None) or "copy"
        if not self._inside:
            self._inside = True
            activity_log.log(f"밖에서 끌어오는 중: 썸네일 영역에 들어옴 (목록 {len(self.model.order)}장)")
        if not self.model.order:                     # 목록이 비어 있으면 막대 없이 그냥 받는다
            self.clear()
            return action
        x, y = self._canvas_xy(event)
        self._autoscroll(y)
        self.show_at(self.canvas.canvasx(x), self.canvas.canvasy(y))
        return action

    def _on_leave(self, event):
        if self._inside:
            activity_log.log("밖에서 끌어오는 중: 썸네일 영역을 벗어남")
        self._inside = False
        self.clear()
        return getattr(event, "action", None) or "copy"

    def _autoscroll(self, y: int):
        h = self.canvas.winfo_height()
        if y < EDGE:
            self.canvas.yview_scroll(-1, "units")
        elif y > h - EDGE:
            self.canvas.yview_scroll(1, "units")

    def show_at(self, cx: float, cy: float):
        """캔버스 좌표 (cx, cy)에 놓으면 들어갈 자리에 파란 막대를 그린다."""
        b = drop_slot.boundary_at(self.view, cx, cy)
        coords = drop_slot.mark_coords(self.view, b, cy)
        self._boundary = b
        try:
            if self._mark is None:
                self._mark = self.canvas.create_rectangle(*coords, fill=DROP_MARK, outline=DROP_MARK, tags=(TAG,))
            else:
                self.canvas.coords(self._mark, *coords)
            self.canvas.tag_raise(self._mark)
        except tk.TclError:
            self._mark = None

    def clear(self):
        if self._mark is not None:
            try:
                self.canvas.delete(self._mark)
            except tk.TclError:
                pass
        self._mark = None
        self._boundary = None

    def _raise(self):
        if self._mark is not None:
            try:
                self.canvas.tag_raise(self._mark)
            except tk.TclError:
                pass

    # ---------------------------------------------------------- 놓을 때
    def anchor_for(self, event) -> Optional[str]:
        """놓은 자리의 뒤쪽 항목 id(새 항목을 그 앞에 넣는다). 썸네일 영역 밖이거나 맨 끝이면 None."""
        boundary = self._boundary
        self._inside = False
        self.clear()
        if getattr(event, "widget", None) is not self.canvas or not self.model.order:
            return None
        try:
            x, y = self._canvas_xy(event)
            boundary = drop_slot.boundary_at(self.view, self.canvas.canvasx(x), self.canvas.canvasy(y))
        except (AttributeError, TypeError, ValueError, tk.TclError):
            pass                                     # 놓은 좌표를 못 받으면 마지막으로 막대를 그린 자리
        order = self.model.order
        if boundary is None or boundary >= len(order):
            return None
        return order[boundary]
