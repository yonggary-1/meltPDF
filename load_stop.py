"""
불러오기 [중단] 버튼(상태 표시줄 윗줄) - 목록에 이미 이미지가 보이는 채로 불러오는 중일 때 쓴다.

불러오는 동안 읽은 이미지를 몇십 장씩 먼저 목록에 넣으므로(incremental_add), 목록이 빈 동안에만 보이는
가운데 안내의 [중단](empty_hint.py)은 금방 사라진다. 그래서 목록에 항목이 있고 불러오기가 진행 중이면
상태 표시줄 윗줄 오른쪽(메모리 미터 왼쪽)에 같은 일을 하는 [불러오기 중단] 버튼을 보여 준다.
누르면 load_queue.cancel(): 지금 작업은 그때까지 읽은 이미지만 남기고, 기다리던 작업은 버린다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from doc_model import DocModel

TEXT = "불러오기 중단"


class LoadStopButton:
    def __init__(self, parent: tk.Misc, model: DocModel, jobs, before: tk.Misc):
        self.model = model
        self.jobs = jobs
        self.before = before                     # 이 위젯 앞(왼쪽)에 놓는다 - 상태 문구 라벨
        self.button = ttk.Button(parent, text=TEXT, command=self._stop)
        self._shown = False
        jobs.on_busy_change(lambda busy: self.update())
        model.subscribe("structure", self.update)

    def _stop(self):
        self.jobs.cancel()
        self.button.state(["disabled"])          # 지금 읽던 몇 장이 끝날 때까지 잠깐 걸릴 수 있다

    def update(self):
        show = self.jobs.pending > 0 and bool(self.model.order)
        if show and not self._shown:
            self.button.state(["!disabled"])
            self.button.pack(side=tk.RIGHT, padx=(10, 0), before=self.before)
        elif not show and self._shown:
            self.button.pack_forget()
        self._shown = show
