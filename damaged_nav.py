"""
[깨진 이미지 N장] 버튼(하단, [전체 삭제] 옆) - 목록에서 빨간 테두리(깨졌거나 못 읽은) 이미지를 찾아가는 버튼(v0.19.6, 사용자 요청).

- N은 지금 목록에서 완전하지 않은(item.damaged - 일부만 읽힘, 머리 복구, 못 읽음 모두) 이미지 수. 항목이 들어오거나
  지워질 때마다 바로 바뀐다(들어온 묶음은 그만큼만 더하고, 지우기 등 다른 변화는 다시 센다 - 수천 장에서도 가볍게).
- 누를 때마다 목록 맨 앞부터 차례로 다음 깨진 이미지를 선택하고, 그 타일이 화면 가운데 오도록 스크롤한다.
  마지막 다음은 다시 처음. 하단 상태 줄에 "깨진 이미지 2/5: 이름"을 보여 준다.
- 버튼 바탕은 옅은 빨강(눈에 띄게). 깨진 이미지가 없으면 회색으로 눌리지 않는다.
- ttk 버튼은 윈도우 테마에서 바탕색이 바뀌지 않아 고전 tk 버튼을 쓴다.
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

BG = "#f6d4d1"            # 옅은 빨강
BG_ACTIVE = "#efb5b0"
FG = "#8a1c14"
BG_OFF = "#e6e6e6"
FG_OFF = "#8a8a8a"


class DamagedNav:
    def __init__(self, parent: tk.Misc, view, model, status, keynav=None):
        self.view = view
        self.model = model
        self.status = status
        self.keynav = keynav
        self.count = 0
        self._last: Optional[str] = None            # 마지막으로 찾아간 항목
        self.button = tk.Button(parent, command=self.next, relief=tk.GROOVE, bd=1, padx=10, pady=1,
                                bg=BG, activebackground=BG_ACTIVE, fg=FG, activeforeground=FG,
                                disabledforeground=FG_OFF, highlightthickness=0, cursor="hand2")
        model.subscribe("structure", self._on_structure)
        self._recount()

    # ---------------------------------------------------------- 개수
    def _on_structure(self):
        added = self.model.added_ids
        if added is not None:
            items = self.model.items
            self.count += sum(1 for i in added if getattr(items.get(i), "damaged", False))
            self._show()
        else:
            self._recount()

    def _recount(self):
        self.count = sum(1 for it in self.model.items.values() if it.damaged)
        self._show()

    def _show(self):
        self.button.configure(text=f"깨진 이미지 {self.count}장")
        if self.count:
            self.button.configure(state=tk.NORMAL, bg=BG, cursor="hand2")
        else:
            self.button.configure(state=tk.DISABLED, bg=BG_OFF, cursor="")

    # ---------------------------------------------------------- 찾아가기
    def next(self):
        order = self.model.order
        items = self.model.items
        damaged = [i for i, iid in enumerate(order) if items[iid].damaged]
        if not damaged:
            self._recount()
            return
        start = -1
        if self._last in items:
            try:
                start = order.index(self._last)
            except ValueError:
                start = -1
        idx = next((i for i in damaged if i > start), damaged[0])     # 다음 것, 끝이면 처음으로
        iid = order[idx]
        self._last = iid
        self.model.select_only(iid)
        if self.keynav is not None:
            self.keynav.current = iid                  # 이어서 방향키로 움직일 때 여기서부터
        self._center(idx)
        n = damaged.index(idx) + 1
        it = items[iid]
        kind = "읽지 못함" if it.unreadable else ("머리 부분 복구" if getattr(it, "repaired", False) else "일부만 표시")
        self.status.set(f"깨진 이미지 {n}/{len(damaged)}: {it.label} ({kind})")
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
