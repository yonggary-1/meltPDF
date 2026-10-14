"""
보이는 타일에만 썸네일 그림 붙이기 - 목록에 수천 장이 있어도 화면 그림(Tk 사진 이미지)은 화면에 보이는 타일과
그 위아래 한 화면 분량에만 만든다. 스크롤해서 벗어난 타일의 그림은 지운다(테두리와 이름 글자는 모든 타일에 그대로 있음).

왜(v0.19.2): 이전에는 목록의 모든 항목마다 화면 그림을 만들어 캔버스에 올려 두었다. 윈도우에서 화면 그림 하나는
그래픽 자원(비트맵)과 메모리를 따로 차지해서, 5천 장쯤 불러오자 Tcl/Tk 내부 오류(0x80000003)로 프로그램이 꺼졌다
(사용자 보고, 충돌 기록에서 화면 스레드가 캔버스에 썸네일을 올리던 중이었음).

- 모델(doc_model)의 photo()/release_photo()로 그림을 만들고 놓는다. 썸네일 데이터(작은 PNG)는 항목에 늘 있으므로
  다시 보일 때 금방 다시 만든다.
- 스크롤, 창 크기 변경, 타일 다시 그리기/옮기기 뒤에 한 번 모아서(after_idle) 갱신한다.
- 그림을 붙인 뒤 드래그 표시(유령 썸네일, 파란 막대)가 그림 아래로 깔리지 않게 타일 화면의 배치 알림을 다시 부른다.
"""
from __future__ import annotations

from typing import Set

from config import GRID_PITCH_Y, LIST_PITCH_Y, MARGIN

MARGIN_SCREENS = 1.0      # 보이는 영역 위아래로 이만큼(화면 높이 배수) 더 미리 그림을 만든다(스크롤이 매끄럽게)


class VisibleThumbs:
    def __init__(self, view, model):
        self.view = view
        self.model = model
        self.canvas = view.canvas
        self._shown: Set[str] = set()       # 지금 그림을 붙여 둔 항목
        self._pending = False
        self._in_update = False
        view.layout_hooks.append(self.schedule)
        view.scroll_hooks.append(self.schedule)
        self.canvas.bind("<Configure>", lambda e: self.schedule(), add="+")

    def schedule(self):
        if self._in_update or self._pending:
            return
        self._pending = True
        try:
            self.canvas.after_idle(self.update)
        except Exception:
            self._pending = False

    def visible_range(self) -> range:
        """그림을 붙일 타일 번호 범위(보이는 곳 + 위아래 여유)."""
        c = self.canvas
        n = len(self.model.order)
        h = max(c.winfo_height(), 1)
        top = c.canvasy(0) - h * MARGIN_SCREENS
        bottom = c.canvasy(h) + h * MARGIN_SCREENS
        if self.view.view_mode_var.get() == "grid":
            cols = self.view.cols()
            r0 = max(int((top - MARGIN) // GRID_PITCH_Y), 0)
            r1 = max(int((bottom - MARGIN) // GRID_PITCH_Y) + 1, 0)
            return range(min(r0 * cols, n), min(r1 * cols, n))
        i0 = max(int((top - MARGIN) // LIST_PITCH_Y), 0)
        i1 = max(int((bottom - MARGIN) // LIST_PITCH_Y) + 1, 0)
        return range(min(i0, n), min(i1, n))

    def update(self):
        self._pending = False
        order = self.model.order
        tiles = self.view.tile_items
        want = {order[i] for i in self.visible_range()}
        # 벗어난 타일: 그림 지우고 놓아준다
        for iid in self._shown - want:
            items = tiles.get(iid)
            if items is not None and items.get("img") is not None:
                try:
                    self.canvas.delete(items["img"])
                except Exception:
                    pass
                items["img"] = None
            self.model.release_photo(iid)
        added = False
        index = None
        for iid in want:
            items = tiles.get(iid)
            if items is None or items.get("img") is not None:
                continue
            if index is None:
                index = {k: i for i, k in enumerate(order)}
            photo = self.model.photo(iid)
            if photo is None:
                continue
            tag = ("tile", f"tile:{iid}")
            items["img"] = self.canvas.create_image(*self.view.img_pos(index[iid]), image=photo, tags=tag)
            added = True
        self._shown = want
        if added:
            self._in_update = True          # 배치 알림이 다시 나를 부르지 않게
            try:
                self.view._run_hooks()
            finally:
                self._in_update = False

    def shown_count(self) -> int:
        return len(self._shown)
