"""
빈 목록 안내 - 목록이 비어 있을 때 작업 영역(썸네일 캔버스) 가운데에 "여기로 끌어다 놓으세요" 안내를 크게 보여 준다.
항목이 하나라도 들어오면 지우고, 목록이 다시 비면 다시 보여 준다. 창 크기가 바뀌면 가운데로 다시 옮긴다.
(예전에는 툴바 아래에 한 줄로 늘 떠 있었다. 순서 바꾸기 안내는 하단 상태 표시줄에 이미 있어서 여기에는 넣지 않는다.)
"""
from __future__ import annotations

import tkinter as tk

from config import HAS_DND
from doc_model import DocModel

TAG = "empty_hint"
COLOR = "#7a7a7a"

if HAS_DND:
    MAIN = "이미지 파일이나 폴더를 여기로 드래그하세요."
    SUB = "(zip/rar/cbz/cbr은 안의 이미지만 꺼내고, PDF는 페이지로 열립니다)"
else:
    MAIN = "[드래그앤드롭 비활성 - tkinterdnd2 미설치]"
    SUB = "위 버튼으로 이미지/폴더/PDF를 추가하세요."


class EmptyHint:
    def __init__(self, canvas: tk.Canvas, model: DocModel):
        self.canvas = canvas
        self.model = model
        model.subscribe("structure", self.update)
        canvas.bind("<Configure>", lambda e: self.update(), add="+")     # 기존 크기 변경 처리(타일 재배치)는 그대로 두고 덧붙인다
        canvas.after_idle(self.update)

    def update(self):
        c = self.canvas
        c.delete(TAG)
        if self.model.order:
            return
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 50:
            return
        x = c.canvasx(w / 2)
        y = c.canvasy(h / 2)
        wrap = max(200, w - 80)
        c.create_text(x, y - 16, text=MAIN, fill=COLOR, font=("", 16, "bold"), width=wrap,
                      justify="center", anchor="s", tags=TAG)
        c.create_text(x, y - 4, text=SUB, fill=COLOR, font=("", 12), width=wrap,
                      justify="center", anchor="n", tags=TAG)
