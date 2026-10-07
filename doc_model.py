"""
문서 모델 - "지금 어떤 페이지들이 어떤 순서로 있고, 무엇이 선택/표지인가"를 들고 있는
유일한 곳. 화면(tkinter 위젯)은 전혀 모른다.

다른 기능 파일들은 이 데이터를 직접 고치지 않고 아래 메서드를 통해서만 바꾼다. 바뀌면
알림(subscribe)을 보내고, 화면 쪽(타일 그리기, 상태 표시줄)이 그 알림을 받아 스스로
갱신한다. 그래서 기능을 하나 고칠 때 다른 기능의 파일을 열 일이 없다.

알림 종류:
  "structure" - 항목이 추가/삭제되었거나 표지가 바뀜  (타일을 전부 다시 만들어야 함)
  "order"     - 순서만 바뀜                            (타일 위치만 옮기면 됨)
  "selection" - 선택만 바뀜                            (타일 색만 바꾸면 됨)
"""
from __future__ import annotations

import io
import tkinter as tk
from typing import Callable, Dict, List, Optional, Set

from PIL import Image, ImageTk

import pdf_core


class DocModel:
    def __init__(self):
        self.items: Dict[str, pdf_core.PageItem] = {}
        self.photo_cache: Dict[str, ImageTk.PhotoImage] = {}
        self.order: List[str] = []             # 페이지 순서(핵심 데이터) - 출력 순서와 동일
        self.selected: Set[str] = set()
        self.cover_id: Optional[str] = None
        # 처음 불러온 파일의 이름(확장자 뺀 것). 내보낼 PDF의 기본 파일 이름이자 이름 일괄 변경의 기본
        # 접두사로 쓴다. 목록이 완전히 비면 다시 "처음"부터 시작한다.
        self.source_name: Optional[str] = None
        self._listeners: Dict[str, List[Callable[[], None]]] = {
            "structure": [], "order": [], "selection": [],
        }

    # ---- 알림
    def subscribe(self, kind: str, fn: Callable[[], None]):
        self._listeners[kind].append(fn)

    def _emit(self, kind: str):
        for fn in list(self._listeners[kind]):
            fn()

    # ---- 처음 불러온 파일 이름
    def note_source(self, name: str):
        """처음 불러온 파일의 이름(확장자 뺀 것, 폴더면 폴더 이름)을 기록한다.
        이미 기록된 이름이 있으면 무시한다 - "처음 던져넣은 파일" 이름을 유지하기 위해서."""
        if self.source_name is None and name:
            self.source_name = name

    def final_order(self) -> List[str]:
        """PDF로 내보낼 때의 실제 페이지 순서(표지가 있으면 맨 앞)."""
        if self.cover_id in self.order:
            return [self.cover_id] + [i for i in self.order if i != self.cover_id]
        return list(self.order)

    def ram_bytes(self) -> int:
        """목록이 메모리에 원본 바이트로 들고 있는 이미지 크기 합계(저장 위치 결정에 쓴다)."""
        return sum(len(it.raster_bytes) for it in self.items.values() if it.raster_bytes)

    # ---- 이름 일괄 변경
    def set_labels(self, labels: Dict[str, str]):
        for iid, label in labels.items():
            if iid in self.items:
                self.items[iid].label = label
        self._emit("structure")

    # ---- 항목 추가/삭제
    @staticmethod
    def _make_photo(item: pdf_core.PageItem) -> ImageTk.PhotoImage:
        return ImageTk.PhotoImage(Image.open(io.BytesIO(item.thumb_bytes)))

    def add(self, items):
        for it in items:
            self.items[it.id] = it
            self.photo_cache[it.id] = self._make_photo(it)
            self.order.append(it.id)
        self._emit("structure")

    def remove_selected(self):
        if not self.selected:
            return
        for iid in list(self.selected):
            if iid in self.order:
                self.order.remove(iid)
            self.items.pop(iid, None)
            self.photo_cache.pop(iid, None)
            if self.cover_id == iid:
                self.cover_id = None
        self.selected.clear()
        if not self.order:
            self.source_name = None
        self._emit("structure")

    def clear(self):
        self.order.clear()
        self.items.clear()
        self.photo_cache.clear()
        self.selected.clear()
        self.cover_id = None
        self.source_name = None
        self._emit("structure")

    # ---- 표지
    def set_cover(self, iid: Optional[str]):
        self.cover_id = iid
        self._emit("structure")

    # ---- 선택
    def select_only(self, iid: str):
        self.selected = {iid}
        self._emit("selection")

    def toggle_select(self, iid: str):
        if iid in self.selected:
            self.selected.discard(iid)
        else:
            self.selected.add(iid)
        self._emit("selection")

    def clear_selection(self):
        self.selected.clear()
        self._emit("selection")

    # ---- 순서 변경
    def move_to_index(self, iid: str, idx: int):
        """iid를 "iid를 뺀 순서"의 idx번째 자리로 옮긴다. 순서가 그대로면 아무것도 안 한다."""
        if iid not in self.order:
            return
        order_wo = [i for i in self.order if i != iid]
        idx = min(max(idx, 0), len(order_wo))
        if order_wo[:idx] + [iid] + order_wo[idx:] == self.order:
            return
        order_wo.insert(idx, iid)
        self.order = order_wo
        self._emit("order")
