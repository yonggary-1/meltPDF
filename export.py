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
import pdf_save_name
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

    BIG_TEXT = "PDF 내보내기"          # 한글 화면 글자(영문 화면을 만들면 "PDF Print" - 사용자 지정)
    BIG_STYLE = "BigExport.TButton"

    def make_button(self, parent: tk.Misc, big: bool = False) -> ttk.Button:
        """내보내기 버튼을 만들어 돌려준다 (어디에 배치할지는 부르는 쪽이 정한다).
        big=True: 툴바 오른쪽 위에 두는 큰 버튼(큰 굵은 글씨, 높이는 툴바 두 줄 - v0.19.5)."""
        if big:
            style = ttk.Style(parent)
            style.configure(self.BIG_STYLE, font=("", 12, "bold"), justify="center", anchor="center")
            self.button = ttk.Button(parent, text=self.BIG_TEXT, style=self.BIG_STYLE, command=self.export_pdf)
        else:
            self.button = ttk.Button(parent, text="PDF로 내보내기", command=self.export_pdf)
        return self.button

    def export_pdf(self):
        model = self.model
        if not model.order:
            messagebox.showinfo(APP_TITLE, "먼저 이미지를 추가하세요.")
            return
        # 원본이 파일/폴더 하나면 그 옆에서 "이름_Reprint.pdf"로, 여럿이면 처음 것의 이름.pdf (pdf_save_name.py)
        start_dir, default_name = pdf_save_name.suggest(model)
        out_path = filedialog.asksaveasfilename(
            title="PDF로 저장", defaultextension=".pdf", filetypes=[("PDF 파일", "*.pdf")],
            initialfile=default_name, **({"initialdir": start_dir} if start_dir else {}),
        )
        if not out_path:
            return

        ordered_items = [model.items[iid] for iid in model.order]
        # 전혀 못 읽은 이미지(X 표시)는 그 자리에 빈 쪽으로 넣고(pdf_core), 끝난 뒤 알린다(v0.19.6)
        skipped = [it.label for it in ordered_items if it.unreadable]
        if len(skipped) == len(ordered_items):
            messagebox.showwarning(APP_TITLE, "PDF에 넣을 수 있는 이미지가 없습니다(모두 읽지 못한 이미지입니다).")
            return
        self._skipped = skipped
        cover_id = model.cover_id
        meta = model.meta.copy()          # 서지 정보(서지 정보 창에서 확인/수정한 값)
        if self.button is not None:
            self.button.configure(state="disabled")
        self.status.set("PDF 생성 중...")

        activity_log.log(f"PDF로 내보내기 시작: {len(ordered_items)}쪽" + (f" (읽지 못한 이미지 {len(skipped)}장은 빈 쪽)" if skipped else ""))

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
            skipped = getattr(self, "_skipped", [])
            if skipped:
                names = "\n".join(skipped[:20]) + (f"\n... 외 {len(skipped) - 20}장" if len(skipped) > 20 else "")
                messagebox.showwarning(APP_TITLE, f"PDF가 생성되었습니다:\n{out_path}\n\n"
                                                  f"읽지 못한 이미지 {len(skipped)}장(X 표시)은 그 자리에 빈 쪽으로 넣었습니다\n"
                                                  f"(쪽 크기: 머리에서 찾은 크기, 없으면 바로 앞 쪽과 같게):\n{names}")
            else:
                messagebox.showinfo(APP_TITLE, f"PDF가 생성되었습니다:\n{out_path}")
