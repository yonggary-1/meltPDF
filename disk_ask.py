"""
"디스크의 임시 폴더를 쓸까요?" 묻는 창 - 꺼낼 이미지가 메모리 한도를 넘을 때(storage_policy) 책/압축 파일(book_loader)과
PDF(pdf_loader)가 함께 쓴다. True = 디스크 사용, False = 이 파일은 불러오지 않음.
"""
from __future__ import annotations

from tkinter import messagebox

from config import APP_TITLE


def fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f}GB"
    return f"{n / 1024 ** 2:.0f}MB"


def ask(estimate: int, limit: int) -> bool:
    return messagebox.askyesno(
        APP_TITLE,
        f"이 파일의 이미지는 압축을 풀면 약 {fmt_size(estimate)}입니다.\n"
        f"메모리 한도(약 {fmt_size(limit)})를 넘어서, 전부 메모리에 올리면 컴퓨터가 느려지거나 "
        f"멈출 수 있습니다.\n\n"
        f"디스크의 임시 폴더를 사용해서 불러올까요?\n"
        f"('아니요'를 누르면 이 파일은 불러오지 않습니다. 설정에서 기본 동작을 바꿀 수 있습니다.)")
