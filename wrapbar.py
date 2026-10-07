"""
WrapBar - 가로 폭이 좁아지면 버튼들을 자동으로 다음 줄로 넘기는 툴바 컨테이너.
(이 파일은 툴바 배치만 담당한다. 어떤 버튼이 들어가는지는 app_window.py가 정한다.)
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional


class WrapBar(tk.Frame):
    """가로 폭이 좁아지면 자식 위젯들을 자동으로 다음 줄로 넘기는(줄바꿈) 툴바 컨테이너.

    pack/grid 대신 place로 직접 배치하고, 폭이 바뀔 때마다(<Configure>) 매번 다시 계산해서
    배치한다. 버튼이 늘어서 한 줄에 다 안 들어가면 필요한 만큼 알아서 여러 줄로 늘어나므로,
    앞으로 버튼/라디오버튼/구분선이 추가되더라도 add()로 추가하기만 하면 되고 창 폭에 따라
    잘리는 문제를 매번 따로 손볼 필요가 없다."""

    def __init__(self, master, pad: int = 4, gap_x: int = 4, gap_y: int = 4, **kwargs):
        super().__init__(master, **kwargs)
        self._items: list = []  # [(widget, gap_before)] - 왼쪽->오른쪽, 위->아래 순서
        self._pad = pad
        self._gap_x = gap_x
        self._gap_y = gap_y
        self._last_width = None
        self.bind("<Configure>", self._on_configure)

    def add(self, widget: tk.Widget, gap_before: int = 0) -> tk.Widget:
        """위젯을 다음 순서로 추가한다. gap_before는 이 위젯 앞에 추가로 둘 간격(px) -
        구분선 앞뒤로 살짝 띄우고 싶을 때 등에 쓴다."""
        self._items.append((widget, gap_before))
        self.relayout()
        return widget

    def _on_configure(self, event):
        if event.width != self._last_width:
            self._last_width = event.width
            self.relayout(width=event.width)

    def relayout(self, width: Optional[int] = None):
        if width is None:
            width = self.winfo_width()
        if width <= 1:
            return

        # 1단계: 위젯들을 폭에 맞춰 여러 줄로 나눈다.
        rows: list = []
        current: list = []
        x = self._pad
        for widget, gap_before in self._items:
            try:
                widget.update_idletasks()
                w = widget.winfo_reqwidth()
            except tk.TclError:
                continue
            extra = gap_before if current else 0
            if current and x + extra + w > width - self._pad:
                rows.append(current)
                current = []
                x = self._pad
                extra = 0
            current.append((widget, w, extra))
            x += extra + w + self._gap_x
        if current:
            rows.append(current)

        # 2단계: 각 줄의 높이(그 줄에서 가장 큰 위젯 기준)를 구해서 실제로 배치한다.
        y = self._pad
        for row in rows:
            row_h = 20
            for widget, _w, _extra in row:
                try:
                    row_h = max(row_h, widget.winfo_reqheight())
                except tk.TclError:
                    pass
            x = self._pad
            for widget, w, extra in row:
                x += extra
                try:
                    widget.place(x=x, y=y, height=row_h)
                except tk.TclError:
                    pass
                x += w + self._gap_x
            y += row_h + self._gap_y

        total_h = (y - self._gap_y + self._pad) if rows else (self._pad * 2)
        try:
            self.configure(height=max(total_h, 10))
        except tk.TclError:
            pass
