"""
프로그램 창 아이콘 - assets/meltPDF.ico(윈도우), assets/meltPDF.png(그 밖)를 창(과 이후 열리는 모든 작은 창)에 붙인다.
exe 파일 자체의 아이콘은 build.bat의 PyInstaller --icon 옵션이 붙인다. 아이콘 그림은 tools/make_icon.py로 만든다.
아이콘 파일이 없거나 읽지 못해도 프로그램은 기본 아이콘으로 그대로 뜬다.
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from typing import Optional


def _asset(name: str) -> Optional[str]:
    for base in (getattr(sys, "_MEIPASS", None), Path(__file__).resolve().parent):
        if base:
            p = Path(base) / "assets" / name
            if p.is_file():
                return str(p)
    return None


def apply(root: tk.Tk) -> None:
    try:
        ico = _asset("meltPDF.ico")
        if os.name == "nt" and ico:
            root.iconbitmap(default=ico)               # default=: 나중에 여는 작은 창(설정, 서지 정보 등)에도 같은 아이콘
            return
        png = _asset("meltPDF.png")
        if png:
            photo = tk.PhotoImage(master=root, file=png)
            root.iconphoto(True, photo)
            root._meltpdf_icon = photo                 # 그림 객체가 사라지지 않게 붙들어 둔다
    except Exception:
        pass
