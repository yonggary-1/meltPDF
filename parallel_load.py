"""
여러 장 동시 처리 - 이미지 썸네일 만들기를 CPU 코어 여러 개로 나눠 하되, 결과는 넣은 순서 그대로 돌려준다.

- 이미지 풀기/줄이기(Pillow)는 파이썬 잠금(GIL)을 풀고 일하므로 스레드로도 코어를 나눠 쓸 수 있다.
- 한꺼번에 다 맡기지 않고 "동시 작업 수 x 2"개까지만 미리 맡긴다: 메모리를 아끼고, [중단]을 누르면 금방 멈추게.
- 동시 작업 수는 코어 수에서 하나를 화면용으로 남기고, 최대 MAX_WORKERS(큰 이미지 여러 장을 동시에 풀면 메모리를 많이 쓰므로).
- should_stop()이 참이 되면 아직 시작하지 않은 일은 버리고 끝낸다(이미 받은 결과까지만 돌려준다).
"""
from __future__ import annotations

import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Iterator, Optional, Tuple

MAX_WORKERS = 8


def worker_count() -> int:
    cpus = os.cpu_count() or 2
    return max(1, min(MAX_WORKERS, cpus - 1 if cpus > 2 else cpus))


def ordered(fn: Callable[[Any], Any], args: Iterable[Any],
            should_stop: Optional[Callable[[], bool]] = None,
            workers: Optional[int] = None) -> Iterator[Tuple[Any, Any, Optional[BaseException]]]:
    """args의 각 값에 fn을 동시에 적용하고 (값, 결과, 예외)를 넣은 순서대로 내준다(예외가 나면 결과는 None)."""
    n = workers or worker_count()
    it = iter(args)
    if n <= 1:                                   # 코어가 하나면 그냥 차례로
        for a in it:
            if should_stop is not None and should_stop():
                return
            try:
                yield a, fn(a), None
            except Exception as e:
                yield a, None, e
        return
    ex = ThreadPoolExecutor(max_workers=n, thread_name_prefix="thumb")
    pending: deque = deque()
    try:
        def fill():
            while len(pending) < n * 2:
                try:
                    a = next(it)
                except StopIteration:
                    return
                pending.append((a, ex.submit(fn, a)))

        fill()
        while pending:
            if should_stop is not None and should_stop():
                return
            a, fut = pending.popleft()
            try:
                yield a, fut.result(), None
            except Exception as e:
                yield a, None, e
            fill()
    finally:
        for _a, fut in pending:
            fut.cancel()
        ex.shutdown(wait=True, cancel_futures=True)
