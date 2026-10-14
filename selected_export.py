"""
[선택된 이미지 내보내기] 버튼 - 목록에서 선택한 이미지를 원본 파일 위치(처음 불러온 파일이 있는 폴더)에 바로 저장한다.
[전체 이미지 내보내기]와 달리 새 폴더를 만들지 않고, 묻는 창 없이 그 폴더 안에 파일로 저장한 뒤
"원본 파일 위치에 파일을 저장했습니다." 안내를 띄운다.

- 저장 내용과 이름 규칙은 전체 이미지 내보내기와 같다(image_export.py): 원본 바이트 그대로, 목록에 보이는 이름,
  PDF 쪽은 그 쪽 안의 원본 이미지. 여러 개를 선택했으면 목록 순서대로 모두 저장한다.
- 그 폴더에 같은 이름의 파일이 이미 있으면 덮어쓰지 않고 " (1)"을 붙여 저장하고 안내에 알린다.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

import activity_log
import bug_report
import image_export
import ui_mailbox
from config import APP_TITLE
from doc_model import DocModel
from status_bar import StatusBar

DONE_TEXT = "원본 파일 위치에 파일을 저장했습니다."
_MAX_LINES = 20


class SelectedExporter:
    def __init__(self, root: tk.Misc, model: DocModel, status: StatusBar):
        self.root = root
        self.model = model
        self.status = status
        self.button: Optional[ttk.Button] = None
        self._busy = False

    def make_button(self, parent: tk.Misc) -> ttk.Button:
        self.button = ttk.Button(parent, text="선택된 이미지 내보내기", command=self.export_selected)
        return self.button

    def export_selected(self):
        if self._busy:
            return
        model = self.model
        ids = [iid for iid in model.order if iid in model.selected]
        if not ids:
            messagebox.showinfo(APP_TITLE, "내보낼 이미지를 목록에서 선택하세요.")
            return
        folder = model.source_dir
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo(APP_TITLE, "원본 파일이 있는 폴더를 알 수 없습니다. [전체 이미지 내보내기]의 [찾아보기]를 쓰세요.")
            return
        plan = image_export.build_plan_into([model.items[i] for i in ids], folder)
        if not plan.entries:
            text = "내보낼 이미지가 없습니다."
            if plan.skipped_pdf_pages:
                text += "\n(선택한 PDF 쪽에는 꺼낼 이미지가 없습니다.)"
            if plan.notes:
                text += "\n" + "\n".join(plan.notes)
            messagebox.showinfo(APP_TITLE, text)
            return

        self._busy = True
        if self.button is not None:
            self.button.configure(state="disabled")
        self.status.set("선택한 이미지 저장 중...")

        def work():
            try:
                result = image_export.write_plan(plan)
                ui_mailbox.post(lambda: self._on_done(plan, result, None))
            except Exception as e:
                ui_mailbox.post(lambda e=e: self._on_done(plan, None, e))   # e는 except 블록이 끝나면 지워지므로 기본값으로 붙잡는다

        threading.Thread(target=work, name="선택이미지내보내기", daemon=True).start()

    def _on_done(self, plan, result, error):
        if error is not None:
            bug_report.note_handled("선택된 이미지 내보내기 실패", error)
        else:
            activity_log.log("선택된 이미지 내보내기 끝")
        self._busy = False
        if self.button is not None:
            self.button.configure(state="normal")
        self.status.refresh()
        if error is not None:
            messagebox.showerror(APP_TITLE, f"이미지 저장 실패:\n{error}")
            return
        written, errors = result
        saved = [e.saved_as for e in plan.entries if e.saved_as]
        lines = saved[:_MAX_LINES] + ([f"... 외 {len(saved) - _MAX_LINES}개"] if len(saved) > _MAX_LINES else [])
        text = DONE_TEXT + f"\n{plan.dest_dir}\n\n" + "\n".join(lines)
        renamed = [e.saved_as for e in plan.entries if e.saved_as and e.saved_as.lower() != e.filename.lower()]
        if plan.renamed or renamed:
            text += "\n\n같은 이름의 파일이 이미 있어 이름 뒤에 번호를 붙였습니다(덮어쓰지 않음)."
        if plan.skipped_pdf_pages:
            text += f"\n\nPDF 쪽 {plan.skipped_pdf_pages}개는 꺼낼 이미지가 없어 건너뛰었습니다."
        if plan.notes:
            text += "\n\n" + "\n".join(plan.notes)
        if errors or not written:
            messagebox.showwarning(APP_TITLE, (text if written else "이미지를 저장하지 못했습니다.")
                                   + "\n\n저장하지 못한 파일:\n" + "\n".join(errors[:_MAX_LINES]))
        else:
            messagebox.showinfo(APP_TITLE, text)
