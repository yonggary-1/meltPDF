"""
임시 저장소 - 압축/책 파일에서 꺼낸 이미지를 메모리 대신 디스크의 임시 폴더에 둔다.
(수백~수천 장짜리 파일을 통째로 메모리에 올리면 버티지 못하기 때문.) 이미지는 원본 바이트 그대로
저장되고, PDF 내보내기는 이 파일 경로를 일반 이미지 파일처럼 읽는다. 프로그램이 끝나면 폴더를 지운다.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid
from typing import Optional

_dir: Optional[str] = None


def _ensure_dir() -> str:
    global _dir
    if _dir is None or not os.path.isdir(_dir):
        _dir = tempfile.mkdtemp(prefix="Image2PDF_")
        atexit.register(cleanup)
    return _dir


def new_path(suffix: str = "") -> str:
    """임시 폴더 안의 새 파일 경로(이름 충돌 없음). 원래 확장자를 유지해서 형식을 알 수 있게 한다."""
    return os.path.join(_ensure_dir(), uuid.uuid4().hex + suffix)


def cleanup() -> None:
    global _dir
    if _dir:
        shutil.rmtree(_dir, ignore_errors=True)
        _dir = None
