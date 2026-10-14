"""
놓을 자리 계산과 파란 삽입 막대 위치 - 썸네일 끌기(drag_reorder.py)와 밖에서 파일 끌어 놓기(file_drop_mark.py)가 함께 쓴다.

"경계선 번호" b(0 ~ 전체 개수)는 화면상 b번째 타일의 앞(왼쪽/위쪽) 경계다. 커서가 타일의 왼쪽(위쪽) 절반이면
그 타일 앞, 오른쪽(아래쪽) 절반이면 그 타일 뒤 경계로 잡는다. 좌표를 직접 계산하므로(가까운 타일 찾기가 아님)
맨 끝 경계에도 항상 닿고, 타일 크기는 상수라 항상 정확하다.
"""
from __future__ import annotations

from typing import Optional

from config import DROP_MARK_W, GRID_PITCH_Y, LIST_GAP, LIST_PITCH_Y, LIST_TILE_H, TILE_H, TILE_W


def boundary_at(view, cx: float, cy: float) -> int:
    """캔버스 좌표(cx, cy)가 가리키는 타일 사이 경계선 번호."""
    total = len(view.model.order)
    top = view.top()
    if view.view_mode_var.get() == "grid":
        g = view.grid()
        col = min(max(int((cx - g.left) // g.step), 0), g.cols - 1)
        row = max(int((cy - top) // GRID_PITCH_Y), 0)
        right_half = (cx - g.left) - col * g.step >= TILE_W / 2
        b = row * g.cols + col + (1 if right_half else 0)
    else:
        row = max(int((cy - top) // LIST_PITCH_Y), 0)
        lower_half = (cy - top) - row * LIST_PITCH_Y >= LIST_TILE_H / 2
        b = row + (1 if lower_half else 0)
    return min(b, total)


def mark_coords(view, boundary: int, cy: Optional[float] = None) -> tuple:
    """boundary번째 경계에 그릴 파란 막대의 사각형 좌표(x0, y0, x1, y1). 막대는 칸 사이 간격의 한가운데에 선다."""
    half = DROP_MARK_W / 2
    top = view.top()
    if view.view_mode_var.get() == "grid":
        g = view.grid()
        cols = g.cols
        r, c = divmod(boundary, cols)
        # 줄이 바뀌는 경계(=윗줄의 오른쪽 끝 = 아랫줄의 맨 앞)는 같은 자리다. 커서가 윗줄에
        # 있거나 목록의 맨 끝이면 윗줄 오른쪽 끝에 그려서 커서 옆에 막대가 보이게 한다.
        if c == 0 and boundary > 0:
            at_end = boundary >= len(view.model.order)
            cursor_row = max(0, int((cy - top) // GRID_PITCH_Y)) if cy is not None else r
            if at_end or cursor_row <= r - 1:
                r, c = r - 1, cols
        if c == 0:
            x = g.left - min(g.gap, g.left) / 2           # 첫 칸 앞: 가장자리 여백 안쪽
        else:
            x = g.left + (c - 1) * g.step + TILE_W + g.gap / 2
        x = max(x, half)
        y = top + r * GRID_PITCH_Y
        return (x - half, y, x + half, y + TILE_H)
    edge = view.top()
    y = max(edge + boundary * LIST_PITCH_Y - LIST_GAP / 2, half)
    return (edge, y - half, edge + max(TILE_W, view.layout_width() - edge * 2), y + half)
