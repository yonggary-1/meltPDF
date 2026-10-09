"""
파일명 변경하기 - 모든 작업을 끝내고 PDF를 만들기 직전에, 목록의 현재 순서(표지가 있으면 표지가 맨 앞)에
맞춰 이름을 `접두사 + 4자리 번호`로 일괄 다시 붙인다. 예: ABC0001.jpg, ABC0002.jpg, ...
"순서와 이름을 통일시키는 것"이 목적이라, 끌어서 순서를 바꾼 뒤에 눌러도 그 순서대로 번호가 매겨진다.

- 바뀌는 것은 목록에 보이는 이름뿐이다(원본 파일과 만들어지는 PDF 내용에는 영향 없음).
- 번호 자릿수는 기본 4자리이고, 페이지가 9999장을 넘으면 자동으로 늘어난다.
- 기본 접두사는 처음 불러온 파일 이름이다.
- (나중에 "여러 이미지를 합쳐 한 페이지로 만든" 항목이 생기면 그 페이지는 뒤에 `_01`, `_02`가 붙는다.
  그 기능을 만들 때 build_names에 이 규칙을 더한다.)
"""
from __future__ import annotations

import tkinter as tk
from pathlib import PurePosixPath
from tkinter import messagebox, ttk
from typing import Dict

import name_codec
import pdf_core
from config import APP_TITLE
from doc_model import DocModel

MIN_DIGITS = 4


def clean_prefix(prefix: str) -> str:
    """파일 이름에 쓸 수 없는 글자를 _로 바꾸고, 윈도우에서 문제되는 끝의 공백/마침표를 없앤다."""
    return name_codec.clean_component(prefix)


def build_names(model: DocModel, prefix: str) -> Dict[str, str]:
    """iid -> 새 이름. 이미지는 원래 확장자를 유지하고, PDF 페이지처럼 원래 파일 이름이 없는 항목은 확장자 없이."""
    prefix = clean_prefix(prefix)
    order = model.final_order()
    width = max(MIN_DIGITS, len(str(len(order))))
    names: Dict[str, str] = {}
    for pos, iid in enumerate(order, start=1):
        item = model.items[iid]
        ext = ""
        if item.kind == "image":
            suffix = PurePosixPath(item.label.replace("\\", "/")).suffix
            if suffix.lower() in pdf_core.IMAGE_EXTS:
                ext = suffix
        names[iid] = f"{prefix}{pos:0{width}d}{ext}"
    return names


class RenamePages:
    def __init__(self, root: tk.Misc, model: DocModel):
        self.root = root
        self.model = model

    def open_dialog(self):
        if not self.model.order:
            messagebox.showinfo(APP_TITLE, "이름을 바꿀 항목이 없습니다.")
            return

        win = tk.Toplevel(self.root)
        win.title("파일명 변경하기")
        win.transient(self.root)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="목록의 현재 순서대로 이름을 '접두사 + 번호'로 다시 붙입니다.\n"
                            "(목록에 보이는 이름만 바뀌고, 원본 파일은 바뀌지 않습니다.)",
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frm, text="접두사 (보통 책 이름 약자):").grid(row=1, column=0, sticky="w", pady=(10, 0))
        prefix_var = tk.StringVar(master=win, value=self.model.source_name or "")
        entry = ttk.Entry(frm, textvariable=prefix_var, width=30)
        entry.grid(row=1, column=1, sticky="w", pady=(10, 0), padx=(6, 0))

        ttk.Label(frm, text="미리보기:").grid(row=2, column=0, sticky="nw", pady=(10, 0))
        preview = tk.Label(frm, text="", justify="left", anchor="w", font=("", 9), fg="#333333")
        preview.grid(row=2, column=1, sticky="w", pady=(10, 0), padx=(6, 0))

        def refresh_preview(*_):
            names = build_names(self.model, prefix_var.get())
            order = self.model.final_order()
            lines = [names[i] for i in order[:3]]
            if len(order) > 4:
                lines.append("...")
            if len(order) > 3:
                lines.append(names[order[-1]])
            preview.configure(text="\n".join(lines))

        prefix_var.trace_add("write", refresh_preview)
        refresh_preview()

        def apply():
            self.model.set_labels(build_names(self.model, prefix_var.get()))
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="적용", command=apply).pack(side=tk.LEFT)
        ttk.Button(btns, text="취소", command=win.destroy).pack(side=tk.LEFT, padx=(6, 0))
        win.bind("<Return>", lambda e: apply())
        win.bind("<Escape>", lambda e: win.destroy())

        # 메인 창 가운데에 띄운다
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        entry.focus_set()
        entry.selection_range(0, tk.END)
        win.grab_set()
