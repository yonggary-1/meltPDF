"""
설정 창 - 압축/책 파일에서 꺼낸 이미지를 어디에 둘지(메모리/디스크)와 메모리 한도를 고른다.
값을 저장하는 일은 settings.py가, 저장된 값을 실제로 쓰는 일은 storage_policy.py가 한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import memory_info
from config import APP_TITLE
from settings import STORAGE_ASK, STORAGE_DISK, STORAGE_RAM, Settings

GB = 1024 ** 3


class SettingsDialog:
    def __init__(self, root: tk.Misc, settings: Settings):
        self.root = root
        self.settings = settings

    def open(self):
        win = tk.Toplevel(self.root)
        win.title("설정")
        win.transient(self.root)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="압축/책 파일에서 꺼낸 이미지를 어디에 둘까요?",
                  font=("", 10, "bold")).grid(row=0, column=0, sticky="w")

        mode_var = tk.StringVar(master=win, value=self.settings.get("storage_mode"))
        choices = (
            (STORAGE_ASK, "메모리에 두고, 너무 크면 디스크를 쓸지 물어봅니다 (기본)"),
            (STORAGE_RAM, "항상 메모리만 씁니다 (묻지 않음 - 모자라면 느려지거나 멈출 수 있음)"),
            (STORAGE_DISK, "항상 디스크 임시 폴더를 씁니다 (느리지만 메모리를 아낌)"),
        )
        for row, (value, text) in enumerate(choices, start=1):
            ttk.Radiobutton(frm, text=text, value=value, variable=mode_var).grid(
                row=row, column=0, sticky="w", pady=(6 if row == 1 else 2, 0))

        limit_row = ttk.Frame(frm)
        limit_row.grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Label(limit_row, text="메모리 한도(GB):").pack(side=tk.LEFT)
        limit_var = tk.StringVar(master=win, value=f"{float(self.settings.get('ram_limit_gb')):g}")
        ttk.Entry(limit_row, textvariable=limit_var, width=8).pack(side=tk.LEFT, padx=(6, 0))
        available = memory_info.available_ram_bytes()
        auto_text = (f"0 = 자동 (지금 남은 메모리 {available / GB:.1f}GB의 절반)" if available
                     else "0 = 자동 (남은 메모리를 알 수 없으면 2GB)")
        ttk.Label(limit_row, text="   " + auto_text, foreground="#555555").pack(side=tk.LEFT)

        ttk.Label(frm, text="이미지 내보내기 기본 폴더:", font=("", 10, "bold")).grid(
            row=5, column=0, sticky="w", pady=(16, 0))
        dir_row = ttk.Frame(frm)
        dir_row.grid(row=6, column=0, sticky="we", pady=(4, 0))
        dir_var = tk.StringVar(master=win, value=str(self.settings.get("image_export_dir") or ""))
        ttk.Entry(dir_row, textvariable=dir_var, width=48).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse():
            chosen = filedialog.askdirectory(title="이미지 내보내기 기본 폴더", parent=win,
                                             initialdir=dir_var.get() or None)
            if chosen:
                dir_var.set(chosen)

        ttk.Button(dir_row, text="찾아보기", command=browse).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(frm, text="비워 두면 지정하지 않은 것입니다. 이 폴더 안에 파일 이름으로 하위 폴더를 만들어 풉니다.",
                  foreground="#555555").grid(row=7, column=0, sticky="w", pady=(2, 0))

        def apply():
            try:
                limit = float(limit_var.get().strip() or "0")
                if limit < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(APP_TITLE, "메모리 한도는 0 이상의 숫자로 입력하세요. (0 = 자동)", parent=win)
                return
            self.settings.set("storage_mode", mode_var.get())
            self.settings.set("ram_limit_gb", limit)
            self.settings.set("image_export_dir", dir_var.get().strip())
            win.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=8, column=0, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="저장", command=apply).pack(side=tk.LEFT)
        ttk.Button(btns, text="취소", command=win.destroy).pack(side=tk.LEFT, padx=(6, 0))
        win.bind("<Escape>", lambda e: win.destroy())

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
