"""
RAR / CBR 읽기 - 압축 파일 안의 이미지를 "파일 이름 순서"(자연 정렬)로 꺼낸다(zip과 같은 규칙).

- 목차(이름, 크기, 암호 여부)는 rarfile 라이브러리가 파이썬으로 직접 읽는다 - 외부 도구가 필요 없다.
- 실제로 압축을 푸는 일은 rar_tool.py가 프로그램에 같이 들어 있는 공식 UnRAR(없으면 설치된 7-Zip 등)에
  한 번에 맡긴다. 그래서 RAR는 메모리 방식이어도 풀리는 동안만 디스크 임시 폴더를 잠깐 쓰고, 끝나면 지운다.
- 이미지는 재인코딩 없이 원본 바이트 그대로 꺼낸다. 암호 걸린 rar, 비정상적으로 큰 항목은 거절한다.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zlib
from pathlib import PurePosixPath
from typing import List, Tuple

import rarfile

import temp_store
from book_common import BookError, ExtractedImage, ExtractResult, ProgressFn, is_image_name, noop_progress
from natural_sort import path_key
import rar_tool

# rarfile은 RAR3/4의 압축된 "압축 파일 주석"을 읽을 때 외부 unrar 도구를 PATH에서 찾는다. 컴퓨터에 그런 도구가 없으면
# 목차를 읽는 단계에서 "Cannot find working tool"로 실패해서 멀쩡한 rar가 열리지 않았다. 우리는 주석이 필요 없으므로
# 읽을 최대 크기를 0으로 줄여 주석 읽기를 건너뛰게 한다(rarfile이 공개한 설정값이다).
rarfile.RAR_MAX_COMMENT = 0

MAX_ENTRY_BYTES = 1024 * 1024 * 1024        # 항목 하나 최대 1GB
MAX_TOTAL_BYTES = 16 * 1024 * 1024 * 1024   # 이미지 전체 합계 최대 16GB


def _open(path: str) -> "rarfile.RarFile":
    try:
        rf = rarfile.RarFile(path)
        if rf.needs_password():         # 파일 내용이나 목차(헤더)가 암호화된 경우
            rf.close()
            raise BookError("암호가 걸린 rar는 아직 지원하지 않습니다.")
        if not rf.infolist():           # 서명만 rar이고 안에 아무것도 읽히지 않는 경우
            rf.close()
            raise BookError("rar 파일이 손상되었거나 비어 있습니다.")
        return rf
    except rarfile.PasswordRequired:
        raise BookError("암호가 걸린 rar는 아직 지원하지 않습니다.")
    except rarfile.NeedFirstVolume:
        raise BookError("여러 조각으로 나뉜 rar입니다. 첫 번째 조각(.part1.rar 또는 .rar)을 선택해 주세요.")
    except (rarfile.NotRarFile, rarfile.BadRarFile):
        raise BookError("rar 파일이 손상되었거나 rar 형식이 아닙니다.")
    except (rarfile.Error, OSError) as e:
        raise BookError(f"rar 파일을 열 수 없습니다: {e}")


def _image_infos(rf: "rarfile.RarFile") -> list:
    return [i for i in rf.infolist() if not i.is_dir() and is_image_name(i.filename.replace("\\", "/"))]


def estimate_bytes(path: str) -> int:
    """꺼낼 이미지들의 압축 해제 후 크기 합계(목차만 읽으므로 빠르다). 알 수 없으면 파일 크기."""
    try:
        with _open(path) as rf:
            return sum(i.file_size for i in _image_infos(rf))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def _collect_images(folder: str) -> List[Tuple[str, str]]:
    """풀어 놓은 폴더 안의 이미지들 -> [(안에서의 이름(/ 구분), 실제 경로)]. 이름 순(자연 정렬)."""
    out = []
    for root, dirs, files in os.walk(folder, followlinks=False):
        for f in files:
            full = os.path.join(root, f)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if is_image_name(rel):
                out.append((rel, full))
    out.sort(key=lambda pair: path_key(pair[0]))
    return out


def _missing_names(infos: list, images: List[Tuple[str, str]]) -> List[str]:
    """목차에는 있는데 풀린 폴더에는 없는 이미지 이름(손상되어 도구가 지운 것). 개수가 같으면 이름 해석 차이일 뿐이므로 없는 것으로 본다."""
    expected = [i.filename.replace("\\", "/") for i in infos]
    if len(images) >= len(expected):
        return []
    got = {rel for rel, _full in images}
    names = [n for n in expected if n not in got]
    return names[: len(expected) - len(images)] if len(names) > len(expected) - len(images) else names


def _damaged_names(infos: list, images: List[Tuple[str, str]]) -> set:
    """풀린 이미지 중 압축 파일에 적힌 CRC32와 맞지 않는(깨진) 것의 이름. 이름/인코딩과 무관하게 내용으로 판별한다.
    CRC가 적혀 있지 않은 항목은 확인할 수 없으므로 건너뛴다."""
    expected = {i.filename.replace("\\", "/"): i.CRC for i in infos if getattr(i, "CRC", None) is not None}
    bad = set()
    for rel, full in images:
        want = expected.get(rel)
        if want is None:
            continue
        crc = 0
        with open(full, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                crc = zlib.crc32(chunk, crc)
        if (crc & 0xFFFFFFFF) != (want & 0xFFFFFFFF):
            bad.add(rel)
    return bad


def extract_rar(path: str, on_progress: ProgressFn = noop_progress,
                to_ram: bool = False) -> List[ExtractedImage]:
    with _open(path) as rf:
        infos = _image_infos(rf)
        if any(i.needs_password() for i in infos):
            raise BookError("암호가 걸린 rar는 아직 지원하지 않습니다.")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        for i in infos:
            if i.file_size > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {i.filename}")
    if not infos:
        return []

    total = len(rf.infolist())
    work = tempfile.mkdtemp(prefix="meltPDF_rar_")
    try:
        tool_warning = rar_tool.extract_all(path, work, lambda n: on_progress(min(n, total), total))
        images = _collect_images(work)
        if not images:
            raise BookError("압축은 풀었지만 이미지를 찾지 못했습니다.")
        if sum(os.path.getsize(full) for _rel, full in images) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        warnings: List[str] = []
        missing = _missing_names(infos, images)
        damaged = _damaged_names(infos, images) if tool_warning else set()
        if damaged:
            shown = ", ".join(sorted(damaged)[:10]) + (f" 외 {len(damaged) - 10}개" if len(damaged) > 10 else "")
            warnings.append(f"손상된 이미지 {len(damaged)}개: {shown} (읽을 수 있는 부분만 표시합니다)")
        if tool_warning or missing:
            if missing:
                shown = ", ".join(missing[:10]) + (f" 외 {len(missing) - 10}개" if len(missing) > 10 else "")
                warnings.append(f"손상되어 풀리지 않은 이미지 {len(missing)}개는 목록에서 빠졌습니다: {shown}")
            if tool_warning:
                warnings.append(tool_warning)
        results = ExtractResult(warnings=warnings)
        for rel, full in images:
            if os.path.getsize(full) > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {rel}")
            if to_ram:
                with open(full, "rb") as f:
                    results.append(ExtractedImage(label=rel, data=f.read(), damaged=rel in damaged))
            else:
                dst = temp_store.new_path(PurePosixPath(rel).suffix.lower())
                shutil.move(full, dst)
                results.append(ExtractedImage(label=rel, path=dst, damaged=rel in damaged))
        on_progress(total, total)
        return results
    except OSError as e:
        raise BookError(f"rar 이미지를 읽지 못했습니다: {e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
