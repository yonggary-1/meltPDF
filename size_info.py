"""
목록 이미지 용량 계산 - 하단 상태 표시줄의 "총 N페이지 (이미지 12.3MB)" 숫자.

내보내기를 했을 때 이미지가 디스크를 차지하는 크기를 셈한다.
- 이미지 항목: 내보낼 때 쓰는 바이트 그대로의 크기(원본 파일 크기, 또는 회전/손상 때문에 다시 만든 PNG의 크기).
  원본 파일 크기는 처음 한 번만 디스크에서 읽고 항목에 기억해 둔다.
- PDF 쪽: 그 쪽에 들어 있는 이미지들의 저장 크기(PDF 안에서 압축된 그대로). 같은 이미지를 여러 쪽이 쓰면 한 번만 센다
  (이미지 내보내기도 한 번만 저장한다). JPEG가 아닌 이미지는 내보낼 때 PNG로 바뀌어 크기가 조금 달라질 수 있어 "약"을 붙인다.
- PDF로 내보낼 때는 여기에 PDF 구조 몇 KB가 더해지고, JPEG가 아닌 이미지는 PDF 안에서 다시 압축되어 크기가 조금 다를 수 있다.
"""
from __future__ import annotations

import os
from typing import Iterable, Tuple

_CACHE_ATTR = "_disk_bytes"


def _image_item_bytes(item) -> int:
    if item.raster_bytes is not None:
        return len(item.raster_bytes)
    cached = getattr(item, _CACHE_ATTR, None)
    if cached is None:
        try:
            cached = os.path.getsize(item.source_path) if item.source_path else 0
        except OSError:
            cached = 0
        setattr(item, _CACHE_ATTR, cached)
    return cached


class Accumulator:
    """용량 합계를 이어서 셈한다: 항목이 들어올 때 들어온 것만 더한다(불러오는 중 묶음마다 목록 전체를 다시 세지 않게 - v0.19.3).
    지우기 등 다른 변화가 있으면 새로 만들어 처음부터 센다."""

    def __init__(self):
        self.total = 0
        self.approx = False
        self._seen = set()

    def add(self, items: Iterable) -> None:
        for item in items:
            if item.kind == "pdf_page":
                self.approx = True
                for xref, n in (item.page_images or {}).items():
                    key = (item.origin_pdf, xref)
                    if key not in self._seen:
                        self._seen.add(key)
                        self.total += n
            else:
                self.total += _image_item_bytes(item)


def total_bytes(items: Iterable) -> Tuple[int, bool]:
    """(이미지 용량 합계, 어림값인가). PDF 쪽이 섞여 있으면 어림값."""
    acc = Accumulator()
    acc.add(items)
    return acc.total, acc.approx


def fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f}GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"
