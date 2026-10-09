"""
책/압축 파일 이미지 추출의 진입점 - 파일 앞부분(시그니처)을 보고 알맞은 읽기 모듈에 넘긴다.
새 포맷은 자기 파일(archive_xxx.py 등)을 만든 뒤 여기 READERS에 한 줄만 추가한다.

확장자가 아니라 시그니처로 판별하는 이유: cbz라는 이름인데 실제로는 rar인 파일(또는 반대)이 흔하다.
"""
from __future__ import annotations

import os
import zipfile
from typing import Callable, List, Optional

import archive_rar
import archive_zip
import book_epub
import book_fb2
from book_common import BookError, ExtractedImage, ProgressFn, noop_progress

# 사용자가 고를 수 있는 확장자(파일 선택 창 필터와 드래그앤드롭 판정에 쓴다)
SUPPORTED_EXTS = (".zip", ".cbz", ".rar", ".cbr", ".epub", ".fb2")


def is_supported(path: str) -> bool:
    return path.lower().endswith(SUPPORTED_EXTS)


def _sniff(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError as e:
        raise BookError(f"파일을 열 수 없습니다: {e}")
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return _sniff_zip(path)
    if head[:7] == b"Rar!\x1a\x07\x00" or head[:8] == b"Rar!\x1a\x07\x01\x00":   # RAR 4 / RAR 5
        return "rar"
    if _is_fb2_text(path):
        return "fb2"
    return None


def _sniff_zip(path: str) -> str:
    """zip 계열을 가른다: epub(META-INF/container.xml이 있음) / fb2.zip(.fb2 파일 하나) / 그 밖의 zip."""
    try:
        with zipfile.ZipFile(path) as zf:
            if book_epub.is_epub(zf):
                return "epub"
            if book_fb2.zip_fb2_name(zf) is not None:
                return "fb2"
    except (zipfile.BadZipFile, OSError):
        pass                                    # 목차가 잘린 zip 등: 일반 zip 읽기(복구 포함)에 맡긴다
    return "zip"


def _is_fb2_text(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return book_fb2.looks_like_fb2(f.read(8192))
    except OSError:
        return False


# 포맷별 읽기 함수: reader(path, on_progress, to_ram) / 꺼낼 이미지 크기 추정 함수: estimator(path)
READERS: dict[str, Callable[[str, ProgressFn, bool], List[ExtractedImage]]] = {
    "zip": archive_zip.extract_zip,
    "rar": archive_rar.extract_rar,
    "epub": book_epub.extract_epub,
    "fb2": book_fb2.extract_fb2,
}
ESTIMATORS: dict[str, Callable[[str], int]] = {
    "zip": archive_zip.estimate_bytes,
    "rar": archive_rar.estimate_bytes,
    "epub": book_epub.estimate_bytes,
    "fb2": book_fb2.estimate_bytes,
}


def estimate_image_bytes(path: str) -> int:
    """파일에서 꺼낼 이미지의 대략적인 총 크기(바이트). 메모리/디스크 중 어디에 둘지 정하는 데 쓴다.
    알 수 없는 형식이면 파일 크기를 돌려준다."""
    try:
        kind = _sniff(path)
    except BookError:
        kind = None
    estimator = ESTIMATORS.get(kind) if kind else None
    if estimator is not None:
        return estimator(path)
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def extract_images(path: str, on_progress: ProgressFn = noop_progress,
                   to_ram: bool = True) -> List[ExtractedImage]:
    """파일 안의 이미지를 꺼내서 돌려준다. 순서는 형식마다 다르다: zip/rar 같은 압축 파일은 이름 순(자연 정렬),
    책 형식(epub/mobi/pdf 등)은 파일에 들어 있는 순서(to_ram이면 메모리, 아니면 디스크 임시 폴더).
    실패하면 BookError."""
    kind = _sniff(path)
    reader = READERS.get(kind) if kind else None
    if reader is None:
        raise BookError("지원하지 않는 파일 형식이거나 손상된 파일입니다.")
    return reader(path, on_progress, to_ram)
