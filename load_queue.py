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
import traceback
from typing import Any, Callable, Optional, Tuple

import activity_log
import ui_mailbox


class LoadCancelled(Exception):
    """[중단]으로 시작하지 않고 버려진 작업에 on_done의 오류로 넘어간다(조용히 무시하면 됨)."""


class LoadQueue:
    def __init__(self, root: tk.Misc):
        self.root = root
        self._jobs: "queue.Queue[Tuple[Callable[[], Any], Callable[[Any, Optional[BaseException]], None]]]" = queue.Queue()
        self._lock = threading.Lock()     # 대기열이 비는 순간과 새 작업이 들어오는 순간의 경합 방지
        self._running = False
        self.pending = 0                  # 넣었지만 아직 결과(on_done)까지 끝나지 않은 작업 수 - 화면 스레드에서만 바꾼다
        self._busy_listeners = []         # 바쁨/한가함이 바뀔 때 부를 함수들(빈 목록 안내의 "이미지 불러오는 중..." 등)
        self._cancel = threading.Event()  # [중단]: 지금 작업은 이것을 보고 멈추고(그때까지 읽은 것은 쓴다), 기다리던 작업은 버린다

    def cancel(self):
        """(화면 스레드) 불러오기 중단. 진행 중인 작업에는 멈추라고 알리고(cancelled()로 확인), 아직 시작하지 않은 작업은 버린다
        (그 작업의 on_done에는 결과 None, 오류 LoadCancelled가 넘어간다)."""
        self._cancel.set()
        activity_log.log("불러오기 [중단] 누름")
        dropped = []
        with self._lock:
            while True:
                try:
                    dropped.append(self._jobs.get_nowait())
                except queue.Empty:
                    break
        if dropped:
            activity_log.log(f"기다리던 작업 {len(dropped)}개 취소")
        for _work, on_done in dropped:
            ui_mailbox.post(lambda cb=on_done: cb(None, LoadCancelled()))

    def cancelled(self) -> bool:
        """(일꾼 스레드에서도 부름) 지금 작업이 [중단]되었는가."""
        return self._cancel.is_set()

    def on_busy_change(self, fn: Callable[[bool], None]):
        self._busy_listeners.append(fn)

    def _set_pending(self, n: int):
        was = self.pending > 0
        self.pending = max(0, n)
        if was != (self.pending > 0):
            for fn in list(self._busy_listeners):
                fn(self.pending > 0)

    def submit(self, work: Callable[[], Any], on_done: Callable[[Any, Optional[BaseException]], None],
               label: str = ""):
        """work()를 일꾼 스레드에서 실행하고, 끝나면 on_done(결과, 오류)를 화면 스레드에서 호출한다.
        오류가 나면 결과는 None이고 오류 객체가 두 번째로 넘어간다. label은 활동 기록에 남길 작업 이름."""
        self._set_pending(self.pending + 1)
        self._seq = getattr(self, "_seq", 0) + 1
        tag = f"작업{self._seq}" + (f"({label})" if label else "")
        activity_log.log(f"{tag} 대기열에 넣음 (대기/진행 {self.pending}개)")

        def finish(result, error, cb=on_done):
            activity_log.log(f"{tag} 결과 처리" + (f" - 오류 {type(error).__name__}" if error else ""))
            try:
                cb(result, error)
            finally:
                self._set_pending(self.pending - 1)

        work = self._logged(work, tag)

        on_done = finish
        with self._lock:
            self._jobs.put((work, on_done))
            if not self._running:
                self._running = True
                threading.Thread(target=self._worker, name="불러오기", daemon=True).start()

    @staticmethod
    def _logged(work, tag):
        def run():
            t0 = activity_log.elapsed()
            activity_log.log(f"{tag} 시작")
            try:
                r = work()
            except BaseException as e:
                if not isinstance(e, LoadCancelled):
                    activity_log.log(f"{tag} 오류: {type(e).__name__}: {e}\n    "
                                     + "".join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip().replace("\n", "\n    "))
                raise
            activity_log.log(f"{tag} 끝 ({activity_log.elapsed() - t0:.1f}초)")
            return r
        return run

    def _worker(self):
        activity_log.log(f"스레드 시작 (id 0x{threading.get_ident():x})")
        while True:
            with self._lock:
                try:
                    work, on_done = self._jobs.get_nowait()
                except queue.Empty:
                    self._running = False
                    return
            self._cancel.clear()               # 새 작업은 중단되지 않은 상태로 시작
            result, error = None, None
            try:
                result = work()
            except BaseException as e:      # 일꾼 스레드가 죽지 않게 모두 잡아서 화면 쪽으로 넘긴다
                error = e
            ui_mailbox.post(lambda r=result, e=error, cb=on_done: cb(r, e))
