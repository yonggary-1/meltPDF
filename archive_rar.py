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
from pathlib import PurePosixPath
from typing import List, Tuple

import rarfile

import temp_store
from book_common import BookError, ExtractedImage, ProgressFn, is_image_name, noop_progress
from natural_sort import path_key
import rar_tool

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
        rar_tool.extract_all(path, work, lambda n: on_progress(min(n, total), total))
        images = _collect_images(work)
        if not images:
            raise BookError("압축은 풀었지만 이미지를 찾지 못했습니다.")
        if sum(os.path.getsize(full) for _rel, full in images) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        results: List[ExtractedImage] = []
        for rel, full in images:
            if os.path.getsize(full) > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {rel}")
            if to_ram:
                with open(full, "rb") as f:
                    results.append(ExtractedImage(label=rel, data=f.read()))
            else:
                dst = temp_store.new_path(PurePosixPath(rel).suffix.lower())
                shutil.move(full, dst)
                results.append(ExtractedImage(label=rel, path=dst))
        on_progress(total, total)
        return results
    except OSError as e:
        raise BookError(f"rar 이미지를 읽지 못했습니다: {e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
