"""
활동 기록 - 프로그램이 무엇을 하고 있었는지를 한 줄씩 파일에 남긴다(버그 리포트의 재료, bug_report.py가 씀).

- 기록 파일: 설정 파일과 같은 곳의 logs 폴더(%APPDATA%\\meltPDF\\logs\\meltPDF_log.txt). 거기에 쓸 수 없으면
  exe(또는 main.py) 옆의 logs. 프로그램을 켤 때마다 지난번 기록은 meltPDF_log_prev.txt로 옮겨 둔다(두 번분만 보관).
- 한 줄 = 시각(밀리초) + 스레드 + 내용. 한 줄 쓸 때마다 바로 디스크에 내보내므로(flush) 프로그램이 갑자기 꺼져도
  그 직전까지 남는다. 최근 줄은 메모리에도 들고 있어 오류 보고서에 바로 붙인다.
- 정상으로 끝나면 마지막 줄에 END_MARK를 쓴다. 다음에 켤 때 지난 기록에 이 줄이 없으면 비정상 종료로 본다.
- 파일 이름은 전체 경로가 아니라 이름만 남긴다(보고서를 다른 사람에게 보낼 때 개인 폴더 구조가 드러나지 않게).
- 기록 자체가 실패해도 프로그램 동작에는 영향이 없다(모든 오류를 삼킨다).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Iterable, List, Optional

LOG_NAME = "meltPDF_log.txt"
PREV_NAME = "meltPDF_log_prev.txt"
END_MARK = "=== 정상 종료 ==="
KEEP_LINES = 400                   # 오류 보고서에 붙일 최근 줄 수(메모리)
MAX_BYTES = 5 * 1024 * 1024        # 한 번 실행에 이보다 커지면 더 쓰지 않는다(무한 반복 기록으로 디스크를 채우지 않게)

_lock = threading.Lock()
_recent: deque = deque(maxlen=KEEP_LINES)
_file = None
_written = 0
_dir: Optional[Path] = None
previous: Optional[Path] = None    # 이번에 켤 때 옮겨 둔 지난번 기록(없으면 None) - 비정상 종료 확인용
_t0 = time.monotonic()


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _candidate_dirs() -> List[Path]:
    # 설정 파일과 같은 곳(exe 옆에 폴더가 생기지 않게). 거기에 못 쓰면 exe(또는 main.py) 옆의 logs.
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return [base / "meltPDF" / "logs", _app_dir() / "logs"]


def log_dir() -> Optional[Path]:
    """기록 파일이 있는 폴더(start() 뒤에만 값이 있음)."""
    return _dir


def start(header_lines: Iterable[str] = ()) -> Optional[Path]:
    """프로그램 시작 때 한 번: 지난 기록을 _prev로 옮기고 새 기록 파일을 연다. 연 파일 경로(실패하면 None)."""
    global _file, _dir, _written, previous
    for d in _candidate_dirs():
        try:
            d.mkdir(parents=True, exist_ok=True)
            cur = d / LOG_NAME
            if cur.exists():
                # 같은 프로그램이 이미 켜져 있어 그쪽이 쓰는 중이면(윈도우) 옮기기가 실패한다 -> 다음 후보 폴더에 쓴다
                os.replace(cur, d / PREV_NAME)
                previous = d / PREV_NAME
            _file = open(cur, "w", encoding="utf-8", newline="\n")
            _dir = d
            _written = 0
            for line in header_lines:
                _write_raw(line)
            return cur
        except OSError:
            _file = None
            continue
    return None


def _write_raw(line: str) -> None:
    global _written
    _recent.append(line)
    if _file is None or _written > MAX_BYTES:
        return
    try:
        _file.write(line + "\n")
        _file.flush()
        _written += len(line) + 1
        if _written > MAX_BYTES:
            _file.write("(기록이 너무 커져 여기서 멈춤)\n")
            _file.flush()
    except (OSError, ValueError):
        pass


def log(text: str) -> None:
    """한 줄 남긴다(어느 스레드에서 불러도 됨)."""
    try:
        now = time.time()
        stamp = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}"
        name = threading.current_thread().name
        name = "화면" if name == "MainThread" else name
        line = f"{stamp} [{name}] {text}"
        with _lock:
            _write_raw(line)
    except Exception:
        pass


def recent(n: int = KEEP_LINES) -> List[str]:
    with _lock:
        return list(_recent)[-n:]


def finish() -> None:
    """정상 종료 때: 끝 표시를 쓰고 닫는다."""
    global _file
    with _lock:
        _write_raw(END_MARK)
        try:
            if _file is not None:
                _file.close()
        except OSError:
            pass
        _file = None


def names(paths, limit: int = 8) -> str:
    """경로 목록 -> 기록용 짧은 글(이름만, 많으면 앞의 몇 개와 개수)."""
    paths = list(paths)
    shown = [Path(str(p)).name or str(p) for p in paths[:limit]]
    more = f" 외 {len(paths) - limit}개" if len(paths) > limit else ""
    return f"{len(paths)}개 [" + ", ".join(shown) + "]" + more


def elapsed() -> float:
    return time.monotonic() - _t0
