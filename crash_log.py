"""
오류 기록(예전 이름 유지용) - 실제 일은 bug_report.py(버그 리포트)와 activity_log.py(활동 기록)가 한다.
다른 파일들이 쓰던 함수 이름을 그대로 두기 위한 얇은 연결만 있다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import activity_log
import bug_report


def write_crash_log(text: str) -> Optional[Path]:
    """프로그램은 계속 동작하는 알림성 기록(예: 폴더 선택 창 대신 작은 창을 띄움) -> 활동 기록에 남긴다."""
    activity_log.log(text.rstrip())
    d = activity_log.log_dir()
    return (d / activity_log.LOG_NAME) if d is not None else None


def report_callback_exception(self, exc, val, tb):
    """tkinter 콜백 안에서 난 예외 -> 버그 리포트 저장 + 알림(예전 방식과 같은 자리에 대입해 쓸 수 있게 남겨 둠)."""
    bug_report._on_tk_exception(exc, val, tb)


def report_startup_failure():
    return bug_report.report_startup_failure()
