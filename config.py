"""
공용 상수 모음 - 이름, 버전, 타일 치수, 색상.
기능 파일들이 서로의 상수를 베끼지 않고 여기서만 가져다 쓴다(값을 고칠 곳이 한 군데).
로직은 넣지 않는다.
"""
from __future__ import annotations

import pdf_core

# tkinterdnd2가 없거나 로드에 실패해도 드래그앤드롭만 빠진 채로 프로그램은 동작해야 한다.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    HAS_DND = False

APP_NAME = "meltPDF"
APP_VERSION = "0.10.0"           # 실제로 확인된(고쳐졌다고 검증된) 진전이 있을 때만 올릴 것 - 같은 버그를 다시 시도하는 빌드는 버전을 올리지 않고 재사용한다
WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"   # 창 타이틀바(버전 포함)
APP_TITLE = APP_NAME                          # 메시지박스 등에는 버전 없이 표시

THUMB_MAX = pdf_core.THUMB_MAX          # 썸네일 최대 변 길이(px) - pdf_core와 동일 기준
DRAG_THRESHOLD = 6                      # 이 픽셀 이상 움직여야 "드래그"로 인정(단순 클릭과 구분)

# 타일 배치 치수 (전부 캔버스에 직접 그리므로 크기를 코드가 정확히 안다 - 위젯 크기를
# 측정할 필요가 없어서 드래그 중 좌표 계산이 항상 정확하다)
MARGIN = 6                              # 격자 전체의 바깥 여백
TILE_W = THUMB_MAX + 18                 # 타일형 칸 하나의 폭
TILE_H = THUMB_MAX + 39                 # 타일형 칸 하나의 높이
GRID_GAP = 12                           # 타일형 칸 사이 간격
LIST_TILE_H = THUMB_MAX + 22            # 목록형 한 줄의 높이
LIST_GAP = 6                            # 목록형 줄 사이 간격
GRID_PITCH_X = TILE_W + GRID_GAP
GRID_PITCH_Y = TILE_H + GRID_GAP
LIST_PITCH_Y = LIST_TILE_H + LIST_GAP

BG_NORMAL = "#f3f3f3"
BG_SELECTED = "#dbeafe"
BG_COVER = "#fff2cc"
BG_DRAGGING = "#cfcfcf"
DAMAGED_OUTLINE = "#d93025"             # 손상되어 일부만 표시되는 이미지 타일의 테두리 색
DAMAGED_OUTLINE_W = 3                   # 그 테두리 두께(px)
DROP_MARK = "#1a73e8"                   # 드래그 중 "여기에 놓인다"를 보여주는 삽입 표시선 색
DROP_MARK_W = 4                         # 삽입 표시선 두께(px)
