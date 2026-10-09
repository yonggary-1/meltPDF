"""
[이미지 내보내기] 버튼과 팝업 창 - 목록의 이미지를 폴더에 파일로 풀어 놓는다.
팝업의 세 버튼: [원본 파일 위치에 폴더 생성 후 풀기] / [설정 폴더에 폴더 생성 후 풀기] / [찾아보기].
어떤 이름을 어떻게 만들지는 image_export.py가 정하고, 여기는 대상 폴더 고르기 + 백그라운드 실행 + 안내만 한다.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

import image_export
from config import APP_TITLE
from doc_model import DocModel
from settings import Settings
from status_bar import StatusBar

_MAX_LINES = 20


class ImageExporter:
    def __init__(self, root: tk.Misc, model: DocModel, status: StatusBar, settings: Settings):
        self.root = root
        self.model = model
        self.status = status
        self.settings = settings
        self.button: Optional[ttk.Button] = None
        self._busy = False

    def make_button(self, parent: tk.Misc) -> ttk.Button:
        self.button = ttk.Button(parent, text="이미지 내보내기", command=self.open_dialog)
        return self.button

    # ---------------------------------------------------------- 팝업
    def open_dialog(self):
        if self._busy:
            return
        if not self.model.order:
            messagebox.showinfo(APP_TITLE, "먼저 이미지를 추가하세요.")
            return
        win = tk.Toplevel(self.root)
        win.title("이미지 내보내기")
        win.transient(self.root)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)
        name = self.model.source_name or "images"
        ttk.Label(frm, text=f"목록의 이미지를 파일로 저장합니다. '{name}' 이름의 새 폴더 안에 풀립니다.\n"
                            "(압축 파일 안의 하위 폴더는 만들지 않고 한 폴더에 펼칩니다.)",
                  justify="left").pack(anchor="w")

        def choose(handler):
            win.destroy()
            handler()

        for text, handler in (("원본 파일 위치에 폴더 생성 후 풀기", self._to_source_dir),
                              ("설정 폴더에 폴더 생성 후 풀기", self._to_setting_dir),
                              ("찾아보기...", self._to_browsed_dir)):
            ttk.Button(frm, text=text, command=lambda h=handler: choose(h)).pack(fill=tk.X, pady=(8, 0))
        ttk.Button(frm, text="취소", command=win.destroy).pack(anchor="e", pady=(12, 0))
        win.bind("<Escape>", lambda e: win.destroy())

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()

    # ---------------------------------------------------------- 대상 폴더 정하기
    def _to_source_dir(self):
        folder = self.model.source_dir
        if not folder or not os.path.isdir(folder):
            messagebox.showinfo(APP_TITLE, "원본 파일이 있는 폴더를 알 수 없습니다. [찾아보기]로 위치를 지정하세요.")
            return
        self._export_into(folder)

    def _to_setting_dir(self):
        folder = str(self.settings.get("image_export_dir") or "")
        if not folder:
            messagebox.showinfo(APP_TITLE, "설정 창에서 '이미지 내보내기 기본 폴더'를 먼저 지정하세요.")
            return
        if not os.path.isdir(folder):
            messagebox.showinfo(APP_TITLE, f"설정한 폴더를 찾을 수 없습니다:\n{folder}\n설정 창에서 다시 지정하세요.")
            return
        self._export_into(folder)

    def _to_browsed_dir(self):
        folder = filedialog.askdirectory(title="이미지를 풀 위치 (이 안에 폴더를 만듭니다)",
                                         initialdir=self.model.source_dir or None)
        if folder:
            self._export_into(folder)

    # ---------------------------------------------------------- 실행
    def _export_into(self, parent_dir: str):
        model = self.model
        items = [model.items[iid] for iid in model.final_order()]
        try:
            plan = image_export.build_plan(items, parent_dir, model.source_name or "images")
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"이미지 내보내기를 시작하지 못했습니다:\n{e}")
            return
        if not plan.entries:
            messagebox.showinfo(APP_TITLE, "내보낼 이미지가 없습니다." + ("\n" + "\n".join(plan.notes) if plan.notes else "") + ("\n(PDF 쪽 " + str(plan.skipped_pdf_pages) + "개에는 꺼낼 이미지가 없습니다.)" if plan.skipped_pdf_pages else ""))
            return
        if plan.renamed:
            messagebox.showinfo(APP_TITLE, self.rename_notice(plan.renamed))

        self._busy = True
        if self.button is not None:
            self.button.configure(state="disabled")
        self.status.set("이미지 저장 중...")

        def progress(done: int, total: int):
            self.root.after(0, lambda: self.status.set(f"이미지 저장 중... {done}/{total}"))

        def work():
            try:
                result = image_export.write_plan(plan, progress)
                self.root.after(0, lambda: self._on_done(plan, result, None))
            except Exception as e:
                self.root.after(0, lambda: self._on_done(plan, None, e))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def rename_notice(renamed) -> str:
        """같은 이름이 겹쳐 이름을 바꾼 목록 안내문."""
        lines = [f"{old} -> {new}" for old, new in renamed]
        shown = "\n".join(lines[:_MAX_LINES])
        if len(lines) > _MAX_LINES:
            shown += f"\n... 외 {len(lines) - _MAX_LINES}건"
        return (f"같은 이름의 이미지가 {len(renamed)}개 있어 이름 뒤에 번호를 붙여 저장합니다.\n"
                "(압축 파일 안의 하위 폴더를 합치면서 이름이 겹쳤습니다.)\n" + shown)

    def _on_done(self, plan, result, error):
        self._busy = False
        if self.button is not None:
            self.button.configure(state="normal")
        self.status.refresh()
        if error is not None:
            messagebox.showerror(APP_TITLE, f"이미지 저장 실패:\n{error}")
            return
        written, errors = result
        text = f"이미지 {written}개를 저장했습니다:\n{plan.dest_dir}"
        if plan.skipped_pdf_pages:
            text += f"\n\nPDF 쪽 {plan.skipped_pdf_pages}개는 꺼낼 이미지가 없거나(글자만 있는 쪽 등) 이미 저장한 이미지뿐이라 건너뛰었습니다."
        if plan.notes:
            text += "\n\n" + "\n".join(plan.notes)
        if errors:
            more = f"\n... 외 {len(errors) - _MAX_LINES}건" if len(errors) > _MAX_LINES else ""
            messagebox.showwarning(APP_TITLE, text + "\n\n저장하지 못한 파일:\n" + "\n".join(errors[:_MAX_LINES]) + more)
        else:
            messagebox.showinfo(APP_TITLE, text)
