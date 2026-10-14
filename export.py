"""
PDF 내보내기 - 현재 목록을 (표지 우선, 순서대로) PDF 파일 하나로 저장한다.
실제 PDF 생성은 pdf_core.export_pdf가 하고, 여기는 저장 위치 묻기 + 백그라운드 실행 + 결과 안내만 한다.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import activity_log
import bug_report
import pdf_core
import ui_mailbox
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
        meta = model.meta.copy()          # 서지 정보(서지 정보 창에서 확인/수정한 값)
        if self.button is not None:
            self.button.configure(state="disabled")
        self.status.set("PDF 생성 중...")

        activity_log.log(f"PDF로 내보내기 시작: {len(ordered_items)}쪽")

        def work():
            try:
                pdf_core.export_pdf(ordered_items, out_path, cover_id=cover_id, meta=meta)
                ui_mailbox.post(lambda: self._on_export_done(out_path, None))
            except Exception as e:
                ui_mailbox.post(lambda e=e: self._on_export_done(out_path, e))   # e는 except 블록이 끝나면 지워지므로 기본값으로 붙잡는다

        threading.Thread(target=work, name="PDF내보내기", daemon=True).start()

    def _on_export_done(self, out_path, error):
        if error:
            bug_report.note_handled("PDF로 내보내기 실패", error)
        else:
            activity_log.log("PDF로 내보내기 끝")
        if self.button is not None:
            self.button.configure(state="normal")
        self.status.refresh()
        if error:
            messagebox.showerror(APP_TITLE, f"PDF 생성 실패:\n{error}")
        else:
            messagebox.showinfo(APP_TITLE, f"PDF가 생성되었습니다:\n{out_path}")
