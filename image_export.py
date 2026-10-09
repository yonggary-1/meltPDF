"""
이미지 내보내기(저장) 핵심 로직 - 화면(tkinter)을 모른다. 목록의 이미지들을 폴더 하나에 파일로 풀어 놓는다.

- 압축 파일 안의 하위 폴더는 만들지 않고 한 폴더에 펼친다(이름만 쓴다). 이름이 겹치면 확장자 앞에 " (1)", " (2)"를
  붙여 겹치지 않게 하고, 어떤 이름이 어떻게 바뀌었는지 기록해 부르는 쪽이 사용자에게 알릴 수 있게 한다(겹침 비교는 윈도우처럼 대소문자 무시).
- 이름은 목록에 보이는 이름(파일명 변경하기 결과 포함)을 따른다. 윈도우가 허용하지 않는 글자만 바꾸고(name_codec.safe_name),
  일본어/중국어 등은 그대로 둔다.
- 내용은 재인코딩하지 않고 목록이 들고 있는 바이트를 그대로 쓴다. 단, 두 경우는 원본 파일이 아니라 목록에 담긴 PNG가 저장된다:
  (1) EXIF 회전 정보가 있어 회전을 반영해 담은 이미지, (2) 손상되어 읽을 수 있는 부분만 담은 이미지.
  이때 확장자는 실제 내용에 맞게 .png로 바뀐다(확장자는 파일 앞부분을 보고 정한다).
- PDF에서 가져온 페이지는 이미지 파일이 아니므로 건너뛴다(PDF 추출 기능은 나중에 따로).
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable, List, Optional, Tuple

import name_codec
import pdf_core

# 파일 앞부분으로 알아낸 형식 -> 확장자와, 같은 형식으로 인정할 확장자들
_FORMAT_EXT = {
    "jpg": ".jpg", "png": ".png", "gif": ".gif", "bmp": ".bmp", "tif": ".tif", "webp": ".webp",
}
_SAME = {
    "jpg": {".jpg", ".jpeg"}, "png": {".png"}, "gif": {".gif"}, "bmp": {".bmp"},
    "tif": {".tif", ".tiff"}, "webp": {".webp"},
}


def sniff_format(head: bytes) -> Optional[str]:
    """파일 맨 앞 바이트로 이미지 형식을 알아낸다(jpg/png/gif/bmp/tif/webp). 모르면 None."""
    if head.startswith(b"\xff\xd8"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _head(item: pdf_core.PageItem) -> bytes:
    if item.raster_bytes is not None:
        return item.raster_bytes[:16]
    with open(item.source_path, "rb") as f:
        return f.read(16)


def _filename_for(item: pdf_core.PageItem) -> str:
    """목록 이름에서 폴더 부분을 떼고 윈도우용으로 정리한 파일 이름. 확장자는 실제 내용에 맞춘다."""
    base = PurePosixPath(item.label.replace("\\", "/")).name or "image"
    name = name_codec.safe_name(base, fallback="image")
    stem, ext = os.path.splitext(name)
    fmt = sniff_format(_head(item))
    if fmt is None:
        return name                                  # 형식을 모르면 이름을 건드리지 않는다
    if ext.lower() in _SAME[fmt]:
        return name
    if ext.lower() in pdf_core.IMAGE_EXTS:
        return stem + _FORMAT_EXT[fmt]               # 확장자가 내용과 다름(예: 회전 반영으로 PNG가 된 .jpg)
    return name + _FORMAT_EXT[fmt]                   # 확장자가 없거나 이미지 확장자가 아님


@dataclass
class Entry:
    item: pdf_core.PageItem
    filename: str


@dataclass
class ExportPlan:
    dest_dir: str                                    # 만들 폴더(아직 없음)
    entries: List[Entry] = field(default_factory=list)
    renamed: List[Tuple[str, str]] = field(default_factory=list)   # (목록에 보이던 이름, 저장할 이름) - 겹쳐서 바뀐 것만
    skipped_pdf_pages: int = 0


def build_plan(items: List[pdf_core.PageItem], parent_dir: str, folder_name: str) -> ExportPlan:
    """items(내보낼 순서)를 parent_dir 안의 새 폴더에 풀 계획을 만든다. 디스크에는 아무것도 만들지 않는다."""
    dest = name_codec.unique_dir(parent_dir, name_codec.safe_name(folder_name or "images", fallback="images"))
    plan = ExportPlan(dest_dir=dest)
    taken: set = set()
    for item in items:
        if item.kind != "image":
            plan.skipped_pdf_pages += 1
            continue
        wanted = _filename_for(item)
        final = name_codec.unique_name(wanted, taken)
        if final != wanted:
            plan.renamed.append((item.label, final))
        plan.entries.append(Entry(item, final))
    return plan


def write_plan(plan: ExportPlan, on_progress: Callable[[int, int], None] = lambda d, t: None) -> Tuple[int, List[str]]:
    """계획대로 폴더를 만들고 파일을 쓴다. (쓴 개수, 실패 설명들)을 돌려준다. 폴더를 못 만들면 예외."""
    os.makedirs(plan.dest_dir, exist_ok=False)
    written, errors = 0, []
    total = len(plan.entries)
    for done, entry in enumerate(plan.entries, start=1):
        out = os.path.join(plan.dest_dir, entry.filename)
        try:
            item = entry.item
            if item.raster_bytes is not None:
                with open(out, "wb") as f:
                    f.write(item.raster_bytes)
            else:
                shutil.copyfile(item.source_path, out)
            written += 1
        except OSError as e:
            errors.append(f"{entry.filename}: {e}")
        on_progress(done, total)
    return written, errors
