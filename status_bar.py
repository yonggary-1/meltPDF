"""
하단 상태 표시줄 - "총 N페이지 | 표지: ..." 문구와, 다른 기능(불러오는 중, 생성 중...)이
잠깐 띄우는 안내 문구를 담당한다. 삭제/내보내기 버튼은 여기 프레임(self.frame) 안에
app_window.py가 배치한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from doc_model import DocModel


class StatusBar:
    def __init__(self, parent: tk.Misc, model: DocModel):
        self.model = model
        # 이 프레임은 화면 가운데(expand) 영역보다 먼저 pack해야 공간을 확보한다.
        self.frame = ttk.Frame(parent, padding=6)
        self.frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.var = tk.StringVar(master=parent)
        # 문구는 윗줄에 혼자 둔다. 아랫줄(app_window가 이 프레임에 pack하는 버튼들과 메모리 미터)이 좁은 창에서 문구 때문에
        # 밀려 잘리지 않게 하려는 것(한 줄에 같이 두면 760px에서 PDF로 내보내기 버튼이 보이지 않았다).
        ttk.Label(self.frame, textvariable=self.var).pack(side=tk.TOP, anchor="w", fill=tk.X, pady=(0, 4))

        model.subscribe("structure", self.refresh)
        model.subscribe("order", self.refresh)
        self.refresh()

    def set(self, text: str):
        self.var.set(text)

    def refresh(self):
        n = len(self.model.order)
        cover_txt = "표지: 지정됨" if self.model.cover_id else "표지: 없음"
        self.var.set(f"총 {n}페이지 | {cover_txt} | 썸네일을 누른 채로 끌면 순서를 바꿀 수 있습니다.")
