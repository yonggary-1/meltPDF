"""
오류 기록 - 실행 중 예외를 조용히 삼키지 않고 crash_log.txt 파일 + 메시지박스로 보여준다.
windowed(exe) 모드에는 콘솔이 없어서 기본 동작(stderr 출력)이 아무 데도 안 보이기 때문에 필수.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from tkinter import messagebox
from typing import Optional

from config import APP_TITLE


def _base_dir() -> Path:
    # exe(onefile)로 빌드된 경우 exe 파일 위치, 아니면 이 스크립트 위치
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def write_crash_log(text: str) -> Optional[Path]:
    try:
        log_path = _base_dir() / "crash_log.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write(text)
        return log_path
    except Exception:
        return None


def report_callback_exception(self, exc, val, tb):
    """tkinter 콜백(버튼 클릭 등) 안에서 난 예외를 로그+메시지박스로 표시. root에 그대로 대입해 쓴다."""
    text = "".join(traceback.format_exception(exc, val, tb))
    log_path = write_crash_log(text)
    msg = f"예상치 못한 오류가 발생했습니다:\n{val}"
    if log_path:
        msg += f"\n\n자세한 로그: {log_path}"
    try:
        messagebox.showerror(APP_TITLE, msg)
    except Exception:
        pass


def report_startup_failure():
    """프로그램이 뜨기도 전에 난 예외를 기록하고 알린다. except 블록 안에서 호출할 것."""
    log_path = write_crash_log(traceback.format_exc())
    try:
        messagebox.showerror(APP_TITLE, f"프로그램을 시작하지 못했습니다.\n자세한 로그: {log_path}")
    except Exception:
        pass
