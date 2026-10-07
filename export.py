"""
PDF 내보내기 - 현재 목록을 (표지 우선, 순서대로) PDF 파일 하나로 저장한다.
실제 PDF 생성은 pdf_core.export_pdf가 하고, 여기는 저장 위치 묻기 + 백그라운드 실행 + 결과 안내만 한다.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pdf_core
from config import APP_TITLE
from doc_model import DocModel
from status_bar import StatusBar


class Exporter:
    def __init__(self, root: tk.Misc, model: DocModel, status: StatusBar):
        self.root = root
        self.model = model
        self.status = status
        self.button = None

    def make_button(self, parent: tk.Misc) -> ttk.Button:
        """내보내기 버튼을 만들어 돌려준다 (어디에 배치할지는 부르는 쪽이 정한다)."""
        self.button = ttk.Button(parent, text="PDF로 내보내기", command=self.export_pdf)
        return self.button

    def export_pdf(self):
        model = self.model
        if not model.order:
            messagebox.showinfo(APP_TITLE, "먼저 이미지를 추가하세요.")
            return
        # 기본 파일 이름 = 처음 불러온 파일 이름 (예: book.epub을 넣었으면 book.pdf)
        default_name = f"{model.source_name}.pdf" if model.source_name else ""
        out_path = filedialog.asksaveasfilename(
            title="PDF로 저장", defaultextension=".pdf", filetypes=[("PDF 파일", "*.pdf")],
            initialfile=default_name,
        )
        if not out_path:
            return

        ordered_items = [model.items[iid] for iid in model.order]
        cover_id = model.cover_id
        if self.button is not None:
            self.button.configure(state="disabled")
        self.status.set("PDF 생성 중...")

        def work():
            try:
                pdf_core.export_pdf(ordered_items, out_path, cover_id=cover_id)
                self.root.after(0, lambda: self._on_export_done(out_path, None))
            except Exception as e:
                self.root.after(0, lambda: self._on_export_done(out_path, e))

        threading.Thread(target=work, daemon=True).start()

    def _on_export_done(self, out_path, error):
        if self.button is not None:
            self.button.configure(state="normal")
        self.status.refresh()
        if error:
            messagebox.showerror(APP_TITLE, f"PDF 생성 실패:\n{error}")
        else:
            messagebox.showinfo(APP_TITLE, f"PDF가 생성되었습니다:\n{out_path}")
