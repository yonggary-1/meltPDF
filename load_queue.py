"""
불러오기 대기열 - 이미지/폴더/PDF/압축 파일 불러오기 작업을 "넣은 순서대로 하나씩" 처리한다.

작업마다 따로 스레드를 돌리면 작은 파일이 먼저 끝나서 목록에 먼저 들어가 버린다(넣은 순서 뒤집힘).
여기서는 일꾼 스레드 하나가 작업을 차례로 실행하고, 결과도 넣은 순서대로 화면 스레드에 전달한다.
(화면을 건드리는 일은 전부 on_done 안에서 - 화면 스레드에서 - 해야 한다.)
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Any, Callable, Optional, Tuple


class LoadQueue:
    def __init__(self, root: tk.Misc):
        self.root = root
        self._jobs: "queue.Queue[Tuple[Callable[[], Any], Callable[[Any, Optional[BaseException]], None]]]" = queue.Queue()
        self._lock = threading.Lock()     # 대기열이 비는 순간과 새 작업이 들어오는 순간의 경합 방지
        self._running = False
        self.pending = 0                  # 넣었지만 아직 결과(on_done)까지 끝나지 않은 작업 수 - 화면 스레드에서만 바꾼다
        self._busy_listeners = []         # 바쁨/한가함이 바뀔 때 부를 함수들(빈 목록 안내의 "이미지 불러오는 중..." 등)

    def on_busy_change(self, fn: Callable[[bool], None]):
        self._busy_listeners.append(fn)

    def _set_pending(self, n: int):
        was = self.pending > 0
        self.pending = max(0, n)
        if was != (self.pending > 0):
            for fn in list(self._busy_listeners):
                fn(self.pending > 0)

    def submit(self, work: Callable[[], Any], on_done: Callable[[Any, Optional[BaseException]], None]):
        """work()를 일꾼 스레드에서 실행하고, 끝나면 on_done(결과, 오류)를 화면 스레드에서 호출한다.
        오류가 나면 결과는 None이고 오류 객체가 두 번째로 넘어간다."""
        self._set_pending(self.pending + 1)

        def finish(result, error, cb=on_done):
            try:
                cb(result, error)
            finally:
                self._set_pending(self.pending - 1)

        on_done = finish
        with self._lock:
            self._jobs.put((work, on_done))
            if not self._running:
                self._running = True
                threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            with self._lock:
                try:
                    work, on_done = self._jobs.get_nowait()
                except queue.Empty:
                    self._running = False
                    return
            result, error = None, None
            try:
                result = work()
            except BaseException as e:      # 일꾼 스레드가 죽지 않게 모두 잡아서 화면 쪽으로 넘긴다
                error = e
            self.root.after(0, lambda r=result, e=error, cb=on_done: cb(r, e))
