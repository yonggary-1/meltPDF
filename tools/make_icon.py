"""
프로그램 아이콘 그리기 - 세로로 긴 그림 액자(가장자리가 물결처럼 굽은 장식 테두리) 안에 세로로 긴 단순한 도장 모양.
한 가지 색만 쓰고 바탕은 투명하다(외부 이미지와 글꼴을 쓰지 않고 직접 그림).
결과: assets/meltPDF.ico (16~256px 여러 크기, exe와 창 아이콘), assets/meltPDF.png (256px, 리눅스 등 창 아이콘)
사용: python tools/make_icon.py   (Pillow만 필요)

- 액자: 네모의 각 변을 같은 물결로 굽힌 바깥선과 안쪽선 사이를 칠해, 굵기가 고른 굽은 띠로 만든다.
- 도장: 둥근 머리에서 아래로 갈수록 좁아지는 손잡이 + 좁은 받침 + 몸통. 액자 안쪽에 닿지 않게 사방에 여백을 둔다.
- 아이콘 칸은 정사각형이고, 그림은 세로로 긴 직사각형이라 좌우는 투명하게 비운다.
- 작은 크기(16~32px)에서는 손잡이 허리가 사라지지 않게 굵게 한다.
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "assets")
SS = 4                                            # 계단 현상을 줄이려고 4배로 그린 뒤 줄인다
COLOR = (140, 86, 40, 255)                        # 한 가지 색(갈색) - 밝은/어두운 작업 표시줄 모두에서 보이는 중간 밝기
CLEAR = (0, 0, 0, 0)

# 64칸 격자 기준 크기
CENTER = (13, 6, 51, 58)         # 액자 띠의 가운데 선(세로로 긴 네모)
BAND = 6.0                       # 액자 띠 굵기
WAVE = 1.5                       # 물결 높이
WAVES = 2                        # 한 변의 물결 수: 모서리와 가운데가 바깥으로, 그 사이 두 곳이 안으로 굽는다
MARGIN = 4.5                     # 도장과 액자 안쪽 사이의 최소 여백


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _wavy(x0, y0, x1, y1, amp, steps=60):
    """네모의 각 변을 cos 물결로 굽힌 닫힌 다각형(64칸 격자 좌표). 모서리는 두 변이 함께 바깥으로 나와 장식처럼 도드라진다."""
    pts = []
    sides = (((x0, y0), (x1, y0), (0, -1)), ((x1, y0), (x1, y1), (1, 0)),
             ((x1, y1), (x0, y1), (0, 1)), ((x0, y1), (x0, y0), (-1, 0)))
    for (ax, ay), (bx, by), (nx, ny) in sides:
        for i in range(steps):
            t = i / steps
            off = amp * math.cos(2 * math.pi * WAVES * t)
            pts.append((ax + (bx - ax) * t + nx * off, ay + (by - ay) * t + ny * off))
    return pts


def draw(size: int) -> Image.Image:
    small = size <= 32
    S = size * SS
    im = Image.new("RGBA", (S, S), CLEAR)
    d = ImageDraw.Draw(im)
    u = S / 64.0

    def P(x, y):
        return (x * u, y * u)

    def circle(cx, cy, r, fill=COLOR):
        d.ellipse([(cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u], fill=fill)

    cx0, cy0, cx1, cy1 = CENTER
    h = BAND / 2

    # 액자: 물결 둘레(바깥)를 칠하고, 같은 물결의 안쪽을 비운다 -> 굵기가 고른 굽은 띠
    d.polygon([P(x, y) for x, y in _wavy(cx0 - h, cy0 - h, cx1 + h, cy1 + h, WAVE)], fill=COLOR)
    d.polygon([P(x, y) for x, y in _wavy(cx0 + h, cy0 + h, cx1 - h, cy1 - h, WAVE)], fill=CLEAR)

    # 도장: 큰 둥근 손잡이 + 목 + 몸통. 안쪽 구멍(물결이 가장 안으로 들어온 곳 기준)에서 사방 여백을 둔다.
    ix0, iy0, ix1, iy1 = cx0 + h + WAVE, cy0 + h + WAVE, cx1 - h - WAVE, cy1 - h - WAVE
    mx = (ix0 + ix1) / 2
    y_top, y_bot = iy0 + MARGIN, iy1 - MARGIN
    # 손잡이: 둥근 머리에서 아래로 갈수록 부드럽게 좁아지는 한 덩어리 윤곽(좌우 대칭)
    head_r = 6.2                                   # 머리 반폭
    head_ry = 7.8                                  # 머리 위쪽의 세로 반지름(위로 조금 긴 둥근 머리)
    waist = 2.6 if not small else 3.0              # 손잡이 아래 끝(가장 좁은 곳) 반폭
    collar_h, base_h = 2.6, 8.0
    base_w = (ix1 - ix0) - 2 * MARGIN
    handle_h = (y_bot - y_top) - collar_h - base_h + 0.6
    pts_l, pts_r = [], []
    steps = 80
    for i in range(steps + 1):
        y = handle_h * i / steps
        if y <= head_ry:                           # 머리 위쪽 반타원
            w = head_r * math.sqrt(max(0.0, 1 - ((head_ry - y) / head_ry) ** 2))
        else:
            t = (y - head_ry) / (handle_h - head_ry)
            w = head_r + (waist - head_r) * _smooth(t)     # 머리 -> 아래 끝까지 좁아지기만 한다(다시 벌어지지 않음)
        pts_l.append(P(mx - w, y_top + y))
        pts_r.append(P(mx + w, y_top + y))
    d.polygon(pts_l + pts_r[::-1], fill=COLOR)
    cy = y_top + handle_h - 0.3                    # 손잡이와 몸통 사이의 좁은 받침
    d.rounded_rectangle([*P(mx - base_w * 0.32, cy), *P(mx + base_w * 0.32, cy + collar_h + 0.3)],
                        radius=round(0.6 * u), fill=COLOR)
    d.rounded_rectangle([*P(mx - base_w / 2, y_bot - base_h), *P(mx + base_w / 2, y_bot)],
                        radius=round(1.6 * u), fill=COLOR)
    alpha = im.getchannel("A").resize((size, size), Image.LANCZOS)   # 모양(투명도)만 줄이고
    out = Image.new("RGBA", (size, size), COLOR[:3] + (0,))
    out.putalpha(alpha)                                               # 색은 어디서나 정확히 한 가지로
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    images = [draw(s) for s in sizes]
    big = images[-1]
    big.save(os.path.join(OUT, "meltPDF.ico"), format="ICO", sizes=[(s, s) for s in sizes],
             append_images=images[:-1])
    big.save(os.path.join(OUT, "meltPDF.png"))
    return sizes, images


if __name__ == "__main__":
    main()
    print("assets/meltPDF.ico, assets/meltPDF.png")
