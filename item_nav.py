"""
"조건에 맞는 이미지 N장" 찾아가기 버튼의 공통 부분 - [깨진 이미지 N장](damaged_nav.py)과 [페이지 추출 N장](pdf_page_nav.py)이 쓴다.

- N은 지금 목록에서 조건(matches)에 맞는 항목 수. 항목이 들어오거나 지워질 때마다 바로 바뀐다(들어온 묶음은 그만큼만 더하고,
  지우기 등 다른 변화는 다시 센다 - 수천 장에서도 가볍게).
- 누를 때마다 목록 맨 앞부터 차례로 다음 항목을 선택하고, 그 타일이 화면 가운데 오도록 스크롤한다. 마지막 다음은 다시 처음.
  하단 상태 줄에 "이름 2/5: 항목 이름 (설명)"을 보여 준다.
- 버튼 바탕은 옅은 색(눈에 띄게). 해당 항목이 없으면 회색으로 눌리지 않는다.
- ttk 버튼은 윈도우 테마에서 바탕색이 바뀌지 않아 고전 tk 버튼을 쓴다.
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

BG_OFF = "#e6e6e6"
FG_OFF = "#8a8a8a"


class ItemNav:
    NAME = "항목"                                  # 버튼과 상태 줄에 쓰는 이름("깨진 이미지")
    BG = "#e6e6e6"
    BG_ACTIVE = "#d0d0d0"
    FG = "#202020"

    def __init__(self, parent: tk.Misc, view, model, status, keynav=None):
        self.view = view
        self.model = model
        self.status = status
        self.keynav = keynav
        self.count = 0
        self._last: Optional[str] = None            # 마지막으로 찾아간 항목
        self.button = tk.Button(parent, command=self.next, relief=tk.GROOVE, bd=1, padx=10, pady=1,
                                bg=self.BG, activebackground=self.BG_ACTIVE, fg=self.FG, activeforeground=self.FG,
                                disabledforeground=FG_OFF, highlightthickness=0, cursor="hand2")
        model.subscribe("structure", self._on_structure)
        self._recount()

    # 하위 클래스가 정한다
    def matches(self, item) -> bool:
        raise NotImplementedError

    def describe(self, item) -> str:
        return ""

    # ---------------------------------------------------------- 개수
    def _on_structure(self):
        added = self.model.added_ids
        if added is not None:
            items = self.model.items
            self.count += sum(1 for i in added if i in items and self.matches(items[i]))
            self._show()
        else:
            self._recount()

    def _recount(self):
        self.count = sum(1 for it in self.model.items.values() if self.matches(it))
        self._show()

    def _show(self):
        self.button.configure(text=f"{self.NAME} {self.count}장")
        if self.count:
            self.button.configure(state=tk.NORMAL, bg=self.BG, cursor="hand2")
        else:
            self.button.configure(state=tk.DISABLED, bg=BG_OFF, cursor="")

    # ---------------------------------------------------------- 찾아가기
    def next(self):
        order = self.model.order
        items = self.model.items
        found = [i for i, iid in enumerate(order) if self.matches(items[iid])]
        if not found:
            self._recount()
            return
        start = -1
        if self._last in items:
            try:
                start = order.index(self._last)
            except ValueError:
                start = -1
        idx = next((i for i in found if i > start), found[0])     # 다음 것, 끝이면 처음으로
        iid = order[idx]
        self._last = iid
        self.model.select_only(iid)
        if self.keynav is not None:
            self.keynav.current = iid                  # 이어서 방향키로 움직일 때 여기서부터
        self._center(idx)
        n = found.index(idx) + 1
        it = items[iid]
        desc = self.describe(it)
        self.status.set(f"{self.NAME} {n}/{len(found)}: {it.label}" + (f" ({desc})" if desc else ""))
        try:
            self.view.canvas.focus_set()
        except tk.TclError:
            pass

    def _center(self, idx: int):
        """idx번째 타일이 화면 가운데 오도록 스크롤한다."""
        v = self.view
        c = v.canvas
        _, y, _, h = v.tile_rect(idx)
        total = max(v.content_height(), 1)
        top = y + h / 2 - c.winfo_height() / 2
        c.yview_moveto(max(top, 0) / total)
