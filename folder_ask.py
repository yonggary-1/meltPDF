"""
끌어다 놓은 폴더에 하위 폴더가 있을 때 묻는 작은 창 - "서브 폴더를 검색할까요?"

- 폴더 바로 안에 이미지가 없을 때: "이미지가 없습니다. 서브 폴더를 검색할까요?" [검색] [취소]
- 폴더 바로 안에 이미지가 있을 때: "이미지가 X장 있습니다. 서브 폴더를 검색할까요?" [검색] [확인]
답을 받을 때까지 기다렸다가 돌려준다(끌어다 놓은 순서대로 처리하기 위해). 창을 그냥 닫거나 Esc는 "아무것도 안 함"이다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

SEARCH = "search"       # 하위 폴더까지 모두
TOP_ONLY = "top"        # 폴더 바로 안의 이미지만([확인])
CANCEL = "cancel"       # 아무것도 안 함([취소], 창 닫기, Esc)


def ask(root: tk.Misc, folder_name: str, top_count: int) -> str:
    win = tk.Toplevel(root)
    win.title(folder_name)
    win.transient(root)
    win.resizable(False, False)
    answer = {"v": CANCEL}

    def done(value: str):
        answer["v"] = value
        win.destroy()

    frm = ttk.Frame(win, padding=16)
    frm.pack(fill=tk.BOTH, expand=True)
    text = ("이미지가 없습니다. 서브 폴더를 검색할까요?" if top_count == 0
            else f"이미지가 {top_count}장 있습니다. 서브 폴더를 검색할까요?")
    ttk.Label(frm, text=text).pack(anchor="w")
    btns = ttk.Frame(frm)
    btns.pack(anchor="e", pady=(14, 0))
    search = ttk.Button(btns, text="검색", command=lambda: done(SEARCH))
    search.pack(side=tk.LEFT)
    if top_count == 0:
        ttk.Button(btns, text="취소", command=lambda: done(CANCEL)).pack(side=tk.LEFT, padx=(6, 0))
    else:
        ttk.Button(btns, text="확인", command=lambda: done(TOP_ONLY)).pack(side=tk.LEFT, padx=(6, 0))
    win.bind("<Escape>", lambda e: done(CANCEL))
    win.protocol("WM_DELETE_WINDOW", lambda: done(CANCEL))

    win.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - win.winfo_reqheight()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    search.focus_set()
    win.grab_set()
    root.wait_window(win)
    return answer["v"]
