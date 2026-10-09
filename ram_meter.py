"""
메모리 미터 - 하단 상태바에 "이 프로그램이 지금 쓰는 메모리"와 "컴퓨터 전체 메모리 사용률"을 보여준다.
몇 초마다 스스로 갱신하고(작업 중 화면을 막지 않는 아주 가벼운 호출만 한다), 값을 알아낼 수 없는 환경이면 아무것도 보여주지 않는다.
값을 알아내는 일은 memory_info.py가 맡고, 여기는 보여주기만 한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

import memory_info

REFRESH_MS = 1500


def format_bytes(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f}GB"
    return f"{n / 1024 ** 2:.0f}MB"


def describe(process: Optional[int], total: Optional[int], available: Optional[int]) -> Optional[tuple]:
    """(글, 컴퓨터 전체 사용률 0~100 또는 None). 프로그램 사용량을 모르면 None(미터를 숨김)."""
    if process is None:
        return None
    text = f"메모리 {format_bytes(process)}"
    used_pct = None
    if total and available is not None and total > 0:
        used_pct = max(0.0, min(100.0, (total - available) * 100.0 / total))
        text += f" | PC {used_pct:.0f}%"
    return text, used_pct


class RamMeter:
    def __init__(self, parent: tk.Misc):
        self.frame = ttk.Frame(parent)
        self.var = tk.StringVar(master=parent)
        ttk.Label(self.frame, textvariable=self.var).pack(side=tk.LEFT)
        self.bar = ttk.Progressbar(self.frame, length=60, maximum=100, mode="determinate")
        self.bar.pack(side=tk.LEFT, padx=(6, 0))
        self._job = None
        self.update_now()

    def update_now(self):
        info = describe(memory_info.process_ram_bytes(), memory_info.total_ram_bytes(),
                        memory_info.available_ram_bytes())
        if info is None:
            self.var.set("")
            self.bar.pack_forget()
        else:
            text, pct = info
            self.var.set(text)
            if pct is None:
                self.bar.pack_forget()
            else:
                self.bar["value"] = pct
                if not self.bar.winfo_manager():
                    self.bar.pack(side=tk.LEFT, padx=(6, 0))
        try:
            self._job = self.frame.after(REFRESH_MS, self.update_now)
        except tk.TclError:
            self._job = None            # 창이 이미 닫힘
