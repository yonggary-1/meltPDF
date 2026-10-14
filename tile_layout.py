"""
타일 배치 계산 - 타일형 보기에서 한 줄에 몇 칸을 놓고, 칸 사이와 창 가장자리 여백을 얼마로 할지 정한다(v0.19.4).

사용자 요청:
- 타일은 가운데 정렬. 남는 폭은 칸 사이와 양쪽 가장자리에 나눠 준다(오른쪽에만 큰 빈 곳이 생기지 않게).
- 최소 간격: 칸 사이 GAP_MIN, 가장자리는 그 두 배(EDGE_MIN).
- 폭이 넉넉해 간격이 벌어지면 칸 사이와 가장자리가 모두 같은 간격이 되는 쪽이 가장 좋다.

계산: 가장자리 최소 여백을 지키면서 들어가는 칸 수 n을 정한 뒤, 모든 간격을 똑같이 나눈 값 s = (남는 폭) / (n + 1)이
EDGE_MIN 이상이면 칸 사이와 가장자리를 모두 s로 한다. 그보다 좁으면 가장자리를 EDGE_MIN으로 두고 남는 것을 칸 사이에 나눈다
(이때 칸 사이는 GAP_MIN 이상 EDGE_MIN 미만). 두 경우가 s = EDGE_MIN에서 끊김 없이 이어진다.
세로 방향: 줄 사이는 GAP_MIN 그대로, 위아래 가장자리는 EDGE_MIN(창 폭에 따라 줄 높이가 바뀌면 스크롤 위치가 흔들리므로 고정).
목록형: 줄 사이 LIST_GAP, 가장자리는 그 두 배.
"""
from __future__ import annotations

from typing import NamedTuple

from config import GRID_GAP, LIST_GAP, TILE_W

GAP_MIN = GRID_GAP              # 칸 사이 최소 간격
EDGE_MIN = GRID_GAP * 2         # 창 가장자리 최소 여백(칸 사이 최소의 두 배)
LIST_EDGE = LIST_GAP * 2        # 목록형 가장자리 여백(줄 사이 간격의 두 배)


class GridLayout(NamedTuple):
    cols: int       # 한 줄의 칸 수
    left: float     # 첫 칸의 왼쪽 x
    gap: float      # 칸 사이 간격
    step: float     # 칸 시작점 사이 거리(TILE_W + gap)


def grid(area_w: float, tile_w: float = TILE_W) -> GridLayout:
    """보이는 폭 area_w(스크롤바 제외)에서의 타일형 배치."""
    n = max(1, int((area_w - 3 * GAP_MIN) // (tile_w + GAP_MIN)))
    spare = area_w - n * tile_w
    if n == 1:
        left = max(spare / 2, 0)
        return GridLayout(1, left, GAP_MIN, tile_w + GAP_MIN)
    even = spare / (n + 1)
    if even >= EDGE_MIN:
        return GridLayout(n, even, even, tile_w + even)
    gap = (spare - 2 * EDGE_MIN) / (n - 1)
    return GridLayout(n, EDGE_MIN, gap, tile_w + gap)
