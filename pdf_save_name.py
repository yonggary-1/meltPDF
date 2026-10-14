"""
PDF 저장 창의 처음 위치와 기본 파일 이름(사용자 요청).

- 파일 하나 또는 폴더 하나만 불러왔으면: 저장 창이 그 파일/폴더가 있는 폴더에서 열리고,
  기본 이름은 "원본이름_Reprint.pdf"(파일은 확장자 뺀 이름, 폴더는 폴더 이름).
  예) D:\\책\\book.epub -> D:\\책 에서 book_Reprint.pdf / D:\\사진\\여행 폴더 -> D:\\사진 에서 여행_Reprint.pdf
  원본이 PDF여도 이름이 달라 원본을 덮어쓰지 않는다.
- 여러 개를 불러왔으면 예전처럼: 처음 불러온 것의 이름.pdf, 위치는 운영체제가 정한다(보통 마지막으로 저장한 곳).
- 같은 파일을 두 번 넣은 것은 하나로 센다. 목록을 모두 지우면 다시 처음부터 센다(doc_model.source_paths).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

SUFFIX = "_Reprint"


def suggest(model) -> Tuple[Optional[str], str]:
    """(저장 창을 열 폴더 또는 None, 기본 파일 이름)."""
    name = model.source_name or ""
    if not name:
        return None, ""
    if len(model.source_paths) == 1:
        folder = model.source_dir
        if not folder or not os.path.isdir(folder):
            folder = None                     # 원본 폴더가 사라졌으면 운영체제에 맡긴다
        return folder, f"{name}{SUFFIX}.pdf"
    return None, f"{name}.pdf"
