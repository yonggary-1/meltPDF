"""
표지 지정/해제, 선택 삭제, 전체 삭제 - 목록을 바꾸는 명령들(확인 창 포함).
버튼 배치는 app_window.py가 하고, 여기는 각 명령이 하는 일만 담는다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from config import APP_TITLE
from doc_model import DocModel


class PageActions:
    def __init__(self, canvas: tk.Canvas, model: DocModel):
        self.model = model
        canvas.bind("<Delete>", lambda e: self.delete_selected())

    def set_cover_selected(self):
        if not self.model.selected:
            messagebox.showinfo(APP_TITLE, "표지로 지정할 항목을 목록에서 선택하세요.")
            return
        self.model.set_cover(next(iter(self.model.selected)))

    def clear_cover(self):
        self.model.set_cover(None)

    def delete_selected(self):
        self.model.remove_selected()

    def delete_all(self):
        if not self.model.order:
            return
        if not messagebox.askyesno(
            APP_TITLE, "목록의 모든 항목을 삭제할까요? 이 작업은 되돌릴 수 없습니다."
        ):
            return
        self.model.clear()
