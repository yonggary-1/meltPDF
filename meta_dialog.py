"""
서지 정보(Metadata) 창 - 불러온 문서에서 읽은 서지 정보를 보여 주고 고칠 수 있게 한다.
여기서 저장한 값이 PDF로 내보낼 때 들어간다(pdf_meta.apply_meta). 값을 들고 있는 곳은 doc_model(DocModel.meta).

- 처음 값은 "서지 정보가 있는 첫 파일"에서 읽은 것이다. 여러 문서를 불러왔으면 다른 파일의 정보로 바꿔 채울 수 있다.
- 압축 파일(zip/rar/cbz/cbr)과 이미지에는 서지 정보가 없으므로 빈 칸으로 열린다. 직접 입력하면 그대로 들어간다.
- 목록을 모두 지우면 서지 정보도 비워진다(처음 불러온 파일 이름과 같은 규칙).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import book_meta
from book_meta import FIELDS, BookMeta
from config import APP_TITLE
from doc_model import DocModel

_HINTS = {
    "author": "여러 명은 ; 로 구분",
    "keywords": "여러 개는 , 로 구분",
    "language": "예: ko, en, ja, en-US",
    "date": "예: 2020, 2020-05, 2020-05-17",
}
_GREY = "#555555"


class MetaDialog:
    def __init__(self, root: tk.Misc, model: DocModel):
        self.root = root
        self.model = model

    def open(self):
        model = self.model
        win = tk.Toplevel(self.root)
        win.title("서지 정보 (Metadata)")
        win.transient(self.root)
        win.resizable(True, False)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(1, weight=1)

        if model.meta_sources:
            where = f"읽어온 곳: {model.meta_sources[0].source}" if not model.meta_edited else "직접 고친 값입니다."
        else:
            where = "불러온 파일에 서지 정보가 없습니다(압축 파일/이미지에는 없음). 직접 입력할 수 있습니다."
        ttk.Label(frm, text=where, foreground=_GREY).grid(row=0, column=0, columnspan=3, sticky="w")

        row = 1
        source_var = None
        if len(model.meta_sources) > 1:
            pick = ttk.Frame(frm)
            pick.grid(row=row, column=0, columnspan=3, sticky="we", pady=(8, 0))
            ttk.Label(pick, text="파일별로 읽은 정보:").pack(side=tk.LEFT)
            names = [f"{i + 1}. {m.source}" for i, m in enumerate(model.meta_sources)]
            source_var = tk.StringVar(master=win, value=names[0])
            ttk.Combobox(pick, textvariable=source_var, values=names, state="readonly", width=36).pack(
                side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)
            ttk.Button(pick, text="이 정보로 채우기",
                       command=lambda: fill(model.meta_sources[names.index(source_var.get())])).pack(
                side=tk.LEFT, padx=(6, 0))
            row += 1

        vars_: dict = {}
        subject_text = None
        for name, label in FIELDS:
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="nw", pady=(8, 0), padx=(0, 8))
            if name in book_meta.MULTILINE:
                box = ttk.Frame(frm)
                box.grid(row=row, column=1, columnspan=2, sticky="we", pady=(8, 0))
                subject_text = tk.Text(box, height=5, width=56, wrap="word", undo=True, font="TkDefaultFont")
                scroll = ttk.Scrollbar(box, orient=tk.VERTICAL, command=subject_text.yview)
                subject_text.configure(yscrollcommand=scroll.set)
                subject_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                scroll.pack(side=tk.LEFT, fill=tk.Y)
            else:
                var = tk.StringVar(master=win)
                ttk.Entry(frm, textvariable=var, width=56).grid(row=row, column=1, sticky="we", pady=(8, 0))
                vars_[name] = var
                if name in _HINTS:
                    ttk.Label(frm, text=_HINTS[name], foreground=_GREY).grid(
                        row=row, column=2, sticky="w", pady=(8, 0), padx=(8, 0))
            row += 1

        def fill(meta: BookMeta):
            for name, var in vars_.items():
                var.set(getattr(meta, name))
            subject_text.delete("1.0", tk.END)
            subject_text.insert("1.0", meta.subject)

        def current() -> BookMeta:
            m = BookMeta(**{name: var.get() for name, var in vars_.items()})
            m.subject = subject_text.get("1.0", tk.END)
            return m.clean()

        fill(model.meta)

        ttk.Label(frm, text="PDF로 내보낼 때 PDF 문서 속성(제목/저자/주제/키워드)과 XMP 서지 정보로 들어갑니다. "
                            "비워 둔 칸은 넣지 않습니다.",
                  foreground=_GREY, wraplength=560, justify=tk.LEFT).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(12, 0))
        row += 1

        def save():
            new = current()
            errors = book_meta.problems(new)
            if errors:
                messagebox.showerror(APP_TITLE, "\n".join(errors), parent=win)
                return
            if new.values() != model.meta.clean().values():
                new.source = model.meta.source
                model.set_meta(new)
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=3, sticky="we", pady=(16, 0))
        revert = ttk.Button(btns, text="읽어온 값으로 되돌리기",
                            command=lambda: fill(model.meta_sources[0]))
        revert.pack(side=tk.LEFT)
        if not model.meta_sources:
            revert.state(["disabled"])
        ttk.Button(btns, text="모두 지우기", command=lambda: fill(BookMeta())).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="취소", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="저장", command=save).pack(side=tk.RIGHT, padx=(0, 6))
        win.bind("<Escape>", lambda e: win.destroy())

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
        self.win = win                  # 시험에서 창을 찾을 수 있게
        self._fill, self._current, self._save = fill, current, save
