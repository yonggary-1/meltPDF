"""
불러오기 결과를 사용자에게 알리는 기능 - 이미지/폴더/압축 파일 불러오기가 함께 쓴다.

알림은 두 종류를 나눈다.
- 손상된 이미지: 읽을 수 있는 부분만 목록에 넣은 정상 동작이다. 오류가 아니므로 "손상된 이미지 N개가 있습니다"라는 안내(정보 창)로 알린다.
- 불러오지 못한 것: 목록에 넣지 못한 파일. 이것만 경고 창으로 알린다.
- 참고 안내(notes): 오류가 아닌 알림(예: 끝이 잘린 zip을 복구해 읽음). 정보 창.
둘 다 있으면 한 창에 차례로 보여준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from tkinter import messagebox
from typing import List

import activity_log
from config import APP_TITLE

_MAX_LINES = 20


@dataclass
class LoadResult:
    """불러오기 작업 하나의 결과: 목록에 넣을 항목, 못 읽은 것에 대한 설명, 손상된 이미지 이름, 어디서 온 것인지(압축 파일 이름 등)."""
    items: list = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    damaged: List[str] = field(default_factory=list)
    source: str = ""
    notes: List[str] = field(default_factory=list)      # 참고 안내(오류 아님) - 정보 창으로 알린다
    meta: object = None                                  # 파일에서 읽은 서지 정보(book_meta.BookMeta) - 문서 형식만
    cancelled: bool = False                              # [중단]으로 도중에 멈춘 작업(읽은 데까지만 들어 있음)
    unreadable: List[str] = field(default_factory=list)  # 전혀 못 읽어 X 표시 상자로 넣은 이미지("이름: 이유")
    repaired: List[str] = field(default_factory=list)    # 머리 부분이 깨져 복구해 읽은 이미지


def _lines(names: List[str]) -> str:
    shown = "\n".join(names[:_MAX_LINES])
    return shown + (f"\n... 외 {len(names) - _MAX_LINES}건" if len(names) > _MAX_LINES else "")


def build_message(result: LoadResult) -> str:
    """보여줄 글. 알릴 것이 없으면 빈 문자열."""
    parts = []
    if result.errors:
        parts.append("일부를 불러오지 못했습니다:\n" + _lines(result.errors))
    if result.unreadable:
        where = f" ({result.source})" if result.source else ""
        parts.append(f"읽지 못한 이미지 {len(result.unreadable)}개가 있습니다{where}.\n"
                     "목록에는 X 표시 상자와 빨간 테두리로 넣었습니다. PDF에는 그 자리에 빈 쪽으로 들어가고, "
                     "이미지 내보내기는 원본 파일을 그대로 저장합니다.\n" + _lines(result.unreadable))
    if result.repaired:
        where = f" ({result.source})" if result.source else ""
        parts.append(f"머리 부분이 깨진 이미지 {len(result.repaired)}개를 복구해 넣었습니다{where}.\n"
                     "빨간 테두리로 구분되며, 내보낼 때는 복구한 데이터를 씁니다.\n" + _lines(result.repaired))
    if result.damaged:
        where = f" ({result.source})" if result.source else ""
        parts.append(f"손상된 이미지 {len(result.damaged)}개가 있습니다{where}.\n"
                     "읽을 수 있는 부분만 표시하며, 빨간 테두리로 구분됩니다.\n" + _lines(result.damaged))
    for note in result.notes:
        parts.append(note)
    return "\n\n".join(parts)


def show(result: LoadResult) -> None:
    activity_log.log(f"불러오기 결과{' (' + result.source + ')' if result.source else ''}: {len(result.items)}장, 손상 {len(result.damaged)},"
                     f" 머리복구 {len(result.repaired)}, X표시 {len(result.unreadable)}, 못 넣음 {len(result.errors)}{', 중단됨' if result.cancelled else ''}"
                     + (f" - 첫 오류: {result.errors[0][:200]}" if result.errors else ""))
    text = build_message(result)
    if not text:
        return
    if result.errors or result.unreadable:
        messagebox.showwarning(APP_TITLE, text)
    else:
        messagebox.showinfo(APP_TITLE, text)
