"""
ZIP / CBZ 읽기 - 압축 파일 안의 이미지를 "파일 이름 순서"(자연 정렬)로 꺼낸다.

- zip은 안의 파일에 의미 있는 순서가 없다(압축한 도구/시점에 따라 저장 순서가 제각각). 그래서
  저장 순서가 아니라 경로 이름 순으로 정렬한다 - 정렬 규칙은 natural_sort.py (2 < 10, 폴더 단위 비교).
- 이미지는 재인코딩 없이 원본 바이트 그대로 꺼낸다(메모리 또는 디스크 임시 폴더 - 호출하는 쪽이 고른다).
- 윈도우 한글 zip(이름이 cp949인데 UTF-8 표시가 없는 것)의 깨진 이름을 복원한다. 이름은 목록 표시용이고
  순서와는 무관하다.
- 암호 걸린 zip, 비정상적으로 큰 항목(압축 폭탄)은 사유를 알려 주고 거절한다.
"""
from __future__ import annotations

import io
import os
import zipfile
import zlib
from pathlib import PurePosixPath
from typing import List

from natural_sort import path_key
from book_common import BookError, ExtractedImage, ExtractResult, ProgressFn, is_image_name, noop_progress
import temp_store

MAX_ENTRY_BYTES = 1024 * 1024 * 1024        # 항목 하나 최대 1GB
MAX_TOTAL_BYTES = 16 * 1024 * 1024 * 1024   # 이미지 전체 합계 최대 16GB
_CHUNK = 1024 * 1024
_NAME_ENCODINGS = ("utf-8", "cp949", "cp932", "gbk")


def _entry_name(info: zipfile.ZipInfo) -> str:
    """항목 이름을 사람이 읽을 수 있게 복원한다. 파이썬은 UTF-8 표시(0x800)가 없으면 cp437로
    읽으므로, 그 경우 원래 바이트로 되돌려서 UTF-8 -> cp949 -> cp932 -> gbk 순으로 해석해 본다."""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            raw = name.encode("cp437")
        except UnicodeEncodeError:
            raw = None
        if raw is not None:
            for enc in _NAME_ENCODINGS:
                try:
                    name = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
    return name.replace("\\", "/")


def _copy_limited(src, dst, name: str, expected_crc: int = None) -> bool:
    """src의 내용을 dst로 옮긴다. 데이터가 끝까지 정상이면 True, 중간에 깨졌거나(압축 데이터 오류) 체크섬이 안 맞으면
    False(읽은 데까지는 dst에 남는다). 디스크 쓰기 오류 등은 그대로 예외."""
    if hasattr(src, "_expected_crc"):
        src._expected_crc = None            # zipfile이 체크섬이 틀리면 마지막 덩어리를 버리고 예외를 내므로, 체크섬은 아래에서 직접 확인한다
    written = 0
    crc = 0
    while True:
        try:
            chunk = src.read(_CHUNK)
        except (zipfile.BadZipFile, zlib.error, EOFError):
            return False                    # 압축 데이터가 중간에서 깨짐 - 여기까지 읽은 것만 남긴다
        if not chunk:
            break
        written += len(chunk)
        if written > MAX_ENTRY_BYTES:       # 헤더의 크기를 속이는 경우 대비
            raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name}")
        crc = zlib.crc32(chunk, crc)
        dst.write(chunk)
    return expected_crc is None or (crc & 0xFFFFFFFF) == (expected_crc & 0xFFFFFFFF)


def estimate_bytes(path: str) -> int:
    """꺼낼 이미지들의 압축 해제 후 크기 합계(목차만 읽으므로 빠르다). 알 수 없으면 파일 크기."""
    try:
        with zipfile.ZipFile(path) as zf:
            return sum(i.file_size for i in zf.infolist()
                       if not i.is_dir() and is_image_name(_entry_name(i)))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def extract_zip(path: str, on_progress: ProgressFn = noop_progress,
                to_ram: bool = False) -> List[ExtractedImage]:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise BookError("zip 파일이 손상되었거나 zip 형식이 아닙니다.")
    except OSError as e:
        raise BookError(f"파일을 열 수 없습니다: {e}")

    with zf:
        candidates = []
        for info in zf.infolist():
            name = _entry_name(info)
            if not info.is_dir() and is_image_name(name):
                candidates.append((info, name))
        candidates.sort(key=lambda pair: path_key(pair[1]))   # 이름 순(자연 정렬)

        if any(info.flag_bits & 0x1 for info, _ in candidates):
            raise BookError("암호가 걸린 zip은 아직 지원하지 않습니다.")
        if sum(info.file_size for info, _ in candidates) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")

        results = ExtractResult()
        total = len(candidates)
        for done, (info, name) in enumerate(candidates, start=1):
            if info.file_size > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name}")
            try:
                damaged = False
                try:
                    src = zf.open(info)
                except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError):
                    src = None                                  # 항목 머리가 깨져 열 수도 없음
                if src is None:
                    results.warnings.append(f"{name}: 손상되어 읽지 못했습니다. 목록에서 뺐습니다.")
                else:
                    with src:
                        if to_ram:
                            buf = io.BytesIO()
                            ok = _copy_limited(src, buf, name, info.CRC)
                            data = buf.getvalue()
                            keep = bool(data)
                            if keep:
                                results.append(ExtractedImage(label=name, data=data, damaged=not ok))
                        else:
                            out_path = temp_store.new_path(PurePosixPath(name).suffix.lower())
                            with open(out_path, "wb") as dst:
                                ok = _copy_limited(src, dst, name, info.CRC)
                            keep = os.path.getsize(out_path) > 0
                            if keep:
                                results.append(ExtractedImage(label=name, path=out_path, damaged=not ok))
                    if not keep:
                        results.warnings.append(f"{name}: 손상되어 읽지 못했습니다. 목록에서 뺐습니다.")
            except OSError as e:
                raise BookError(f"'{name}'을(를) 읽지 못했습니다: {e}")
            on_progress(done, total)
        return results
