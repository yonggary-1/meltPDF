"""
하단 상태 표시줄 - "총 N페이지 (이미지 용량) | 표지: ..." 문구와, 다른 기능(불러오는 중, 생성 중...)이
잠깐 띄우는 안내 문구를 담당한다. 삭제/내보내기 버튼은 여기 프레임(self.frame) 안에
app_window.py가 배치한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import size_info
from doc_model import DocModel


class StatusBar:
    def __init__(self, parent: tk.Misc, model: DocModel):
        self.model = model
        # 이 프레임은 화면 가운데(expand) 영역보다 먼저 pack해야 공간을 확보한다.
        self.frame = ttk.Frame(parent, padding=6)
        self.frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.var = tk.StringVar(master=parent)
        # 윗줄: 문구(왼쪽) + 오른쪽 끝 자리(top_row - app_window가 메모리 미터를 여기 둔다). 아랫줄: app_window가 이 프레임에
        # pack하는 버튼들. 버튼 줄이 좁은 창에서 잘리지 않게 버튼 외의 것은 윗줄로 올린다(760px에서 확인).
        # 문구는 창이 좁으면 뒤쪽이 잘려 보인다(미터를 먼저 오른쪽에 두므로 미터는 잘리지 않음).
        self.top_row = ttk.Frame(self.frame)
        self.top_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.label = ttk.Label(self.top_row, textvariable=self.var)

        self.label.pack(side=tk.LEFT, anchor="w", fill=tk.X, expand=True)   # 미터가 먼저 오른쪽 자리를 잡은 뒤 남는 폭을 쓴다
        self._acc = None                   # 용량 합계(size_info.Accumulator) - 항목이 들어오면 들어온 것만 더한다
        model.subscribe("structure", self._on_structure)
        model.subscribe("order", self.refresh)
        self.refresh()

    def _on_structure(self):
        added = self.model.added_ids
        if added is not None and self._acc is not None:
            self._acc.add(self.model.items[i] for i in added)
        else:
            self._acc = None               # 지우기/표지/이름 등: 다음 refresh에서 처음부터 센다
        self.refresh()

    def set(self, text: str):
        self.var.set(text)

    def refresh(self):
        n = len(self.model.order)
        cover_txt = "표지: 지정됨" if self.model.cover_id else "표지: 없음"
        if self._acc is None:
            self._acc = size_info.Accumulator()
            self._acc.add(self.model.items[i] for i in self.model.order)
        size, approx = self._acc.total, self._acc.approx
        size_txt = f" (이미지 {'약 ' if approx else ''}{size_info.fmt_size(size)})" if n else ""
        self.var.set(f"총 {n}페이지{size_txt} | {cover_txt} | 썸네일을 누른 채로 끌면 순서를 바꿀 수 있습니다.")
