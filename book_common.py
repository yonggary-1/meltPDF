"""
책/압축 파일에서 이미지 꺼내기 기능들이 함께 쓰는 공통 부분 - 오류 종류, 결과 자료형,
"이 이름이 이미지 파일인가" 판정. 포맷별 파일(archive_zip.py 등)은 서로를 모르고 여기만 안다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Optional

import pdf_core

# on_progress(done, total) - total을 모르면 0
ProgressFn = Callable[[int, int], None]


class BookError(Exception):
    """사용자에게 그대로 보여줘도 되는 사유(한국어)를 담은 오류."""


@dataclass
class ExtractedImage:
    """꺼낸 이미지 한 장. 원본 바이트 그대로이고, 메모리(data)나 디스크 임시 파일(path) 중 한쪽에 있다."""
    label: str                       # 목록에 보여줄 이름(파일 안에서의 경로)
    data: Optional[bytes] = None     # 메모리에 둔 경우
    path: Optional[str] = None       # 디스크 임시 폴더에 둔 경우
    damaged: bool = False            # 압축 파일의 체크섬과 맞지 않는(깨진) 이미지 - 읽을 수 있는 부분만이라도 쓴다


class ExtractResult(list):
    """꺼낸 이미지 목록(그냥 list처럼 쓰면 됨) + 사용자에게 알려야 할 경고들(예: 손상되어 빼놓은 파일).
    경고가 있어도 나머지 이미지는 정상적으로 쓴다."""

    def __init__(self, items=(), warnings=None):
        super().__init__(items)
        self.warnings = list(warnings or [])


def is_image_name(name: str) -> bool:
    """압축 파일 안 항목 이름이 "목록에 넣을 이미지"인가. 폴더, 맥 메타데이터, 숨김 파일은 제외."""
    norm = name.replace("\\", "/")
    if not norm or norm.endswith("/"):
        return False
    parts = PurePosixPath(norm).parts
    if "__MACOSX" in parts or parts[-1].startswith("._"):
        return False
    return PurePosixPath(norm).suffix.lower() in pdf_core.IMAGE_EXTS


def noop_progress(done: int, total: int) -> None:
    return None
