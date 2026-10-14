"""
불러오는 중에 조금씩 목록에 넣기 - 이미지를 다 읽을 때까지 기다리지 않고, 읽은 만큼 몇십 장씩 묶어 화면에 먼저 보여 준다.

- 일꾼 스레드에서 push(항목)로 하나씩 넘기면, BATCH장이 모이거나 INTERVAL초가 지날 때마다 화면 스레드로 넘겨
  model.add(묶음)을 부른다(타일 화면은 새로 붙은 타일만 그린다 - tile_view.rebuild 참고).
- 작업이 끝나면 일꾼 스레드에서 finish()를 불러 남은 것까지 넘긴다. 대기열(load_queue)의 완료 알림(on_done)은
  그 뒤에 화면 스레드로 넘어가므로(같은 root.after 줄에서 넣은 순서대로 실행됨) on_done이 불릴 때는 항목이 이미 다 들어가 있다.
- before(항목 id)를 주면 끝이 아니라 그 항목 앞에 넣는다. 묶음마다 같은 항목 앞에 넣으므로 순서가 그대로 이어진다.
  도중에 그 항목이 지워지면 앞서 넣은 항목 바로 뒤에 이어 넣는다(앞서 넣은 것도 없으면 끝).
- 처음 묶음을 넣기 직전에 before_first()를 한 번 부른다(책 파일의 서지 정보를 알리는 데 쓴다).
- 묶음을 넣은 뒤 상태 표시줄 문구는 마지막 진행 문구(예: "이미지 불러오는 중... 120/800")로 되돌린다
  (모델 알림이 상태 표시줄을 "총 N페이지"로 바꾸기 때문).
"""
from __future__ import annotations

import time
from typing import Callable, List, Optional

BATCH = 24            # 한 번에 넣는 최대 장수(너무 잘게 넣으면 화면 갱신이 잦아져 오히려 느려진다)
INTERVAL = 0.4        # 이만큼 지나면 덜 모였어도 넣는다(큰 이미지를 천천히 읽을 때도 화면이 움직이게)
FIRST_INTERVAL = 0.15 # 첫 묶음은 더 빨리 넣어 "읽기 시작했다"가 바로 보이게


class Feeder:
    def __init__(self, root, model, status=None, before_first: Optional[Callable[[], None]] = None,
                 before: Optional[str] = None):
        self.root = root
        self.before = before          # 이 항목 앞에 넣는다(None이면 끝) - 목록 중간에 끌어다 놓은 경우
        self.model = model
        self.status = status
        self.before_first = before_first
        self._batch: List = []
        self._last = time.monotonic()
        self._first = True
        self.progress_text: Optional[str] = None
        self.count = 0                # 지금까지 화면 쪽으로 넘긴 항목 수
        self._last_id: Optional[str] = None   # (화면 스레드) 마지막으로 넣은 항목

    def push(self, item) -> None:
        """(일꾼 스레드) 항목 하나를 넘긴다."""
        self._batch.append(item)
        wait = FIRST_INTERVAL if self._first else INTERVAL
        if len(self._batch) >= BATCH or time.monotonic() - self._last >= wait:
            self._flush()

    def finish(self) -> None:
        """(일꾼 스레드) 남은 항목을 모두 넘긴다. 작업 함수가 끝나기 전에 부른다."""
        if self._batch:
            self._flush()

    def _flush(self) -> None:
        batch, self._batch = self._batch, []
        self._last = time.monotonic()
        self.count += len(batch)
        first, self._first = self._first, False
        text = self.progress_text
        self.root.after(0, lambda: self._add_on_ui(batch, first, text))

    def _add_on_ui(self, batch, first: bool, text: Optional[str]) -> None:
        if first and self.before_first is not None:
            self.before_first()
        self._keep_place()
        self.model.add(batch, before=self.before)
        self._last_id = batch[-1].id
        if self.status is not None and text:
            self.status.set(text)

    def _keep_place(self) -> None:
        """(화면 스레드) 불러오는 도중 기준 항목(before)이 지워졌으면, 앞서 넣은 항목 바로 뒤에 이어 넣도록 기준을 바꾼다
        (그냥 끝에 붙이면 한 번에 놓은 이미지가 중간과 끝으로 갈라진다)."""
        if self.before is None or self.before in self.model.items:
            return
        order = self.model.order
        if self._last_id is not None and self._last_id in self.model.items:
            i = order.index(self._last_id) + 1
            self.before = order[i] if i < len(order) else None
        else:
            self.before = None
