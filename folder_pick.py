"""
[폴더 (이미지) 추가] 창 - [폴더 선택] 버튼과 "서브 폴더의 이미지 파일도 전부 추가" 체크 상자.
윈도우의 폴더 고르기 창에는 체크 상자를 넣을 수 없어서, 이 작은 창을 먼저 띄우고 [폴더 선택]을 누르면 폴더 고르기 창을 연다.
체크 상자 상태는 설정에 기억해 다음에도 그대로 보인다. 실제로 이미지를 불러오는 일은 부르는 쪽(file_loader)이 한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

from settings import Settings

SETTING_KEY = "folder_recursive"


def open_folder_pick(root: tk.Misc, settings: Optional[Settings], on_pick: Callable[[str, bool], None]) -> None:
    """창을 띄운다. 폴더를 고르면 on_pick(폴더 경로, 하위 폴더 포함 여부)를 부른다(취소하면 부르지 않음)."""
    win = tk.Toplevel(root)
    win.title("폴더 (이미지) 추가")
    win.transient(root)
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill=tk.BOTH, expand=True)
    ttk.Label(frm, text="폴더 안의 이미지 파일을 이름 순서대로 추가합니다.").pack(anchor="w")

    initial = bool(settings.get(SETTING_KEY)) if settings is not None else False
    recursive = tk.BooleanVar(master=win, value=initial)

    def pick():
        rec = bool(recursive.get())
        if settings is not None:
            settings.set(SETTING_KEY, rec)
        folder = filedialog.askdirectory(title="폴더 선택", parent=win)
        if not folder:
            return                                   # 폴더 고르기를 취소하면 이 창은 남겨 둔다(다시 고르거나 취소)
        win.destroy()
        on_pick(folder, rec)

    row = ttk.Frame(frm)
    row.pack(fill=tk.X, pady=(12, 0))
    ttk.Button(row, text="폴더 선택", command=pick).pack(side=tk.LEFT)
    ttk.Checkbutton(row, text="서브 폴더의 이미지 파일도 전부 추가", variable=recursive).pack(side=tk.LEFT, padx=(10, 0))
    ttk.Button(frm, text="취소", command=win.destroy).pack(anchor="e", pady=(12, 0))
    win.bind("<Escape>", lambda e: win.destroy())

    win.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - win.winfo_reqheight()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    win.grab_set()
