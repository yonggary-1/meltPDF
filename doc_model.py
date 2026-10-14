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
import os
import tkinter as tk
from typing import Callable, Dict, List, Optional, Set

from PIL import Image, ImageTk

import activity_log
import pdf_core
from book_meta import BookMeta


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
        # 처음 불러온 파일이 들어 있는 폴더(폴더를 넣었으면 그 폴더가 들어 있는 폴더). 이미지 내보내기의 "원본 파일 위치".
        self.source_dir: Optional[str] = None
        # 지금까지 불러온 원본(파일/폴더) 경로들. 하나뿐이면 PDF 저장 창이 그 옆에서 "이름_Reprint.pdf"로 열린다(pdf_save_name.py).
        self.source_paths: Set[str] = set()
        # 서지 정보: meta는 PDF로 내보낼 때 쓰는 현재 값(서지 정보 창에서 고친 것 포함), meta_sources는 불러온 파일들에서
        # 읽은 원래 값(읽은 순서). 현재 값은 "서지 정보가 있는 첫 파일"의 것으로 채우고, 사용자가 고친 뒤에는 바꾸지 않는다.
        self.meta: BookMeta = BookMeta()
        self.meta_sources: List[BookMeta] = []
        self.meta_edited = False
        self.added_ids: Optional[Set[str]] = None   # add() 알림 중에만: 새로 넣은 항목 id들
        self.added_at: Optional[int] = None         # add() 알림 중에만: 새 항목이 들어간 첫 자리
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
    def note_source(self, name: str, directory: Optional[str] = None, path: Optional[str] = None):
        """처음 불러온 파일의 이름(확장자 뺀 것, 폴더면 폴더 이름)과, 그 파일이 있는 폴더를 기록한다.
        이미 기록된 이름이 있으면 무시한다 - "처음 던져넣은 파일" 이름을 유지하기 위해서.
        path(원본 파일/폴더의 전체 경로)는 매번 모아 둔다 - 원본이 하나뿐인지 알기 위해서."""
        if path:
            self.source_paths.add(os.path.normcase(os.path.abspath(path)))
        if self.source_name is None and name:
            self.source_name = name
            self.source_dir = directory

    # ---- 서지 정보
    def offer_meta(self, meta: Optional[BookMeta]):
        """불러온 파일에서 읽은 서지 정보를 알린다. 아직 현재 값이 비어 있고 사용자가 고친 적이 없으면 현재 값이 된다."""
        if meta is None or meta.is_empty():
            return
        if not any(m.source == meta.source and m.values() == meta.values() for m in self.meta_sources):
            self.meta_sources.append(meta.copy())
        if not self.meta_edited and self.meta.is_empty():
            self.meta = meta.copy()

    def set_meta(self, meta: BookMeta):
        """서지 정보 창에서 저장한 값."""
        self.meta = meta.copy()
        self.meta_edited = True

    def _reset_meta(self):
        self.meta = BookMeta()
        self.meta_sources = []
        self.meta_edited = False

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

    def photo(self, iid: str) -> Optional[ImageTk.PhotoImage]:
        """(화면 스레드) 항목의 썸네일 화면 그림. 필요할 때 만든다. 화면에 보이는 타일 것만 들고 있다
        (visible_thumbs.py가 벗어난 것은 release_photo로 놓는다 - 수천 장을 모두 만들면 윈도우 그래픽 자원이 바닥남)."""
        p = self.photo_cache.get(iid)
        if p is None and iid in self.items:
            p = self.photo_cache[iid] = self._make_photo(self.items[iid])
        return p

    def release_photo(self, iid: str):
        self.photo_cache.pop(iid, None)

    def add(self, items, before: Optional[str] = None):
        """항목을 넣는다. before가 목록에 있는 항목 id면 그 항목 바로 앞에, 아니면(None, 이미 지워진 항목) 끝에 넣는다
        (파일을 목록 중간에 끌어다 놓은 경우 - file_drop_mark.py. 같은 before로 여러 번 넣으면 넣은 순서대로 이어진다).
        알림을 보내는 동안 added_ids에 새 항목 id들을 적어 둬서, 화면이 새 타일만 그리고 뒤쪽 타일만 옮기게 한다
        (불러오는 중에 몇십 장씩 자주 넣으므로 - incremental_add). 다른 "structure" 알림 때는 None."""
        items = list(items)
        if not items:
            return
        try:
            pos = self.order.index(before) if before is not None else len(self.order)
        except ValueError:
            pos = len(self.order)
        new_ids = []
        for it in items:
            self.items[it.id] = it
            new_ids.append(it.id)
        self.order[pos:pos] = new_ids
        activity_log.log(f"목록에 {len(new_ids)}장 넣음 (자리 {pos}{'=끝' if pos + len(new_ids) == len(self.order) else ''}, 전체 {len(self.order)})")
        self.added_ids = set(new_ids)
        self.added_at = pos
        try:
            self._emit("structure")
        finally:
            self.added_ids = None
            self.added_at = None

    def remove_selected(self):
        if not self.selected:
            return
        activity_log.log(f"선택 삭제 {len(self.selected)}장 (전체 {len(self.order)})")
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
            self.source_dir = None
            self.source_paths.clear()
            self._reset_meta()
        self._emit("structure")

    def clear(self):
        activity_log.log(f"전체 삭제 ({len(self.order)}장)")
        self.order.clear()
        self.items.clear()
        self.photo_cache.clear()
        self.selected.clear()
        self.cover_id = None
        self.source_name = None
        self.source_dir = None
        self.source_paths.clear()
        self._reset_meta()
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
        activity_log.log(f"순서 변경: {self.order.index(iid)} -> {idx}")
        self.order = order_wo
        self._emit("order")
