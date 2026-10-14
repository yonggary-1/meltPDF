"""
화면 스레드 우편함 - 일꾼 스레드(불러오기, 썸네일, 내보내기)가 화면에 할 일을 넘기는 곳. 넘기는 쪽은 절대 기다리지 않는다.

왜(v0.19.3): 예전에는 일꾼 스레드가 root.after(0, 할 일)로 넘겼다. tkinter에서 다른 스레드의 root.after는 화면 스레드가
그 요청을 받아 줄 때까지 기다리므로, 화면 스레드가 바쁘면 썸네일을 만드는 스레드들까지 줄줄이 멈췄다
(수천 장에서 불러오기가 거의 멈춘 원인의 하나). 이제 일꾼 스레드는 할 일을 이 우편함(스레드 안전한 대기열)에 넣기만 하고
곧바로 다음 일을 한다. 화면 스레드는 POLL_MS마다 우편함을 비운다.

- 넣은 순서대로 실행한다(불러오기 묶음 -> 진행 문구 -> 완료 처리 순서가 지켜져야 하므로 모든 일꾼 스레드가 이 우편함 하나를 쓴다).
- 한 번에 BUDGET_MS까지만 처리하고 나머지는 바로 이어서 처리한다(그 사이에 화면 그리기와 마우스 입력이 끼어들 수 있게).
- 할 일 하나가 오류를 내도 나머지는 계속한다(오류는 화면 쪽 오류 처리 - 버그 리포트 - 로 넘긴다).
"""
from __future__ import annotations

import queue
import time
from typing import Callable

POLL_MS = 15          # 우편함을 보는 간격
BUDGET_MS = 40        # 한 번에 처리하는 최대 시간

_q: "queue.SimpleQueue[Callable[[], None]]" = queue.SimpleQueue()
_root = None


def start(root) -> None:
    """(화면 스레드) 창을 만든 뒤 한 번 부른다."""
    global _root
    _root = root
    root.after(POLL_MS, _drain)


def post(fn: Callable[[], None]) -> None:
    """(어느 스레드든) 화면 스레드에서 fn()을 실행하도록 넣는다. 기다리지 않는다."""
    _q.put(fn)


def _drain() -> None:
    root = _root
    end = time.perf_counter() + BUDGET_MS / 1000
    more = False
    while True:
        try:
            fn = _q.get_nowait()
        except queue.Empty:
            break
        try:
            fn()
        except Exception:
            import sys
            try:
                root.report_callback_exception(*sys.exc_info())
            except Exception:
                pass
        if time.perf_counter() > end:
            more = True
            break
    try:
        root.after(1 if more else POLL_MS, _drain)
    except Exception:
        pass                        # 창이 닫힘


def pending() -> int:
    return _q.qsize()
