"""
7z / cb7 읽기 - 7z 압축 안의 이미지를 이름 순(zip/rar와 같은 자연 정렬)으로 꺼낸다. py7zr(LGPL-2.1 이상, 순수 파이썬 +
압축 해제 모듈)을 쓴다.

- py7zr의 WriterFactory로 풀리는 내용을 바로 메모리(BytesIO) 또는 디스크 임시 파일로 받는다(임시 폴더에 이름대로 풀지 않음).
  연속(solid) 압축은 앞에서부터 차례로 풀어야 하므로 한 번에 전부 풀고, 받은 뒤 이름 순으로 정렬한다.
- 암호가 걸린 7z는 열지 않는다(암호를 묻지 않음). 7z는 목차가 파일 끝에 있어 끝이 잘린 파일은 열 수 없다.
- 체크섬(CRC)이 틀린 이미지는 거기까지 받은 것을 손상 표시로 넣고, 그 뒤에 못 받은 이미지는 사유를 알린다.
- 이름은 7z 안에 UTF-16으로 들어 있어 문자 코드 추정이 필요 없다. ".."이 든 이름이나 드라이브 문자로 시작하는 이름은 건너뛴다.
"""
from __future__ import annotations

import io
import os
from pathlib import PurePosixPath
from typing import Dict, List

import temp_store
from archive_zip import MAX_ENTRY_BYTES, MAX_TOTAL_BYTES
from book_common import BookError, ExtractedImage, ExtractResult, ProgressFn, is_image_name, noop_progress
from natural_sort import path_key

MAGIC = b"7z\xbc\xaf\x27\x1c"


def looks_like_7z(head: bytes) -> bool:
    return head.startswith(MAGIC)


def _py7zr():
    try:
        import py7zr
        from py7zr import io as p7io
    except ImportError:
        raise BookError("7z를 열려면 py7zr 패키지가 필요합니다(requirements.txt). 프로그램을 다시 빌드해 주세요.")
    return py7zr, p7io


def _safe(name: str) -> bool:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return ".." not in parts and not (len(name) >= 2 and name[1] == ":")


def _open(path: str):
    py7zr, _ = _py7zr()
    try:
        sz = py7zr.SevenZipFile(path, mode="r")
    except py7zr.exceptions.PasswordRequired:
        raise BookError("암호가 걸린 7z는 열지 않습니다.")
    except (py7zr.exceptions.ArchiveError, EOFError, OSError, ValueError, KeyError, IndexError) as e:
        raise BookError(f"7z 파일이 손상되었거나 끝이 잘렸습니다: {e}")
    return sz


def _candidates(sz) -> list:
    return [i for i in sz.list() if not i.is_directory and is_image_name(i.filename.replace("\\", "/"))
            and _safe(i.filename)]


def estimate_bytes(path: str) -> int:
    try:
        sz = _open(path)
        with sz:
            return sum(i.uncompressed or 0 for i in _candidates(sz))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def extract_7z(path: str, on_progress: ProgressFn = noop_progress, to_ram: bool = False) -> List[ExtractedImage]:
    py7zr, p7io = _py7zr()
    sz = _open(path)
    with sz:
        if sz.needs_password():
            raise BookError("암호가 걸린 7z는 열지 않습니다.")
        cands = _candidates(sz)
        if sum(i.uncompressed or 0 for i in cands) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        for i in cands:
            if (i.uncompressed or 0) > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {i.filename}")
        expected: Dict[str, int] = {i.filename: i.uncompressed or 0 for i in cands}
        total = len(cands)

        class _Out(p7io.Py7zIO):
            """풀리는 내용 하나를 받는 곳. close()가 불리면 그 파일은 체크섬까지 끝까지 맞게 풀린 것이다."""

            def __init__(self, name: str):
                self.name = name
                self.done = False
                self.written = 0
                if to_ram:
                    self.path = None
                    self.f = io.BytesIO()
                else:
                    self.path = temp_store.new_path(PurePosixPath(name).suffix.lower())
                    self.f = open(self.path, "wb")

            def write(self, s) -> int:
                self.written += len(s)
                if self.written > MAX_ENTRY_BYTES:
                    raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {self.name}")
                return self.f.write(s)

            def read(self, size=None) -> bytes:
                return b""

            def seek(self, offset: int, whence: int = 0) -> int:
                return self.f.seek(offset, whence)

            def flush(self) -> None:
                self.f.flush()

            def size(self) -> int:
                return self.written

            def close(self) -> None:
                self.done = True
                factory.finished += 1
                on_progress(factory.finished, total)

        class _Factory(p7io.WriterFactory):
            def __init__(self):
                self.outs: Dict[str, _Out] = {}
                self.finished = 0

            def create(self, filename: str) -> p7io.Py7zIO:
                out = self.outs.get(filename)
                if out is None:
                    out = _Out(filename)
                    self.outs[filename] = out
                return out

        factory = _Factory()
        results = ExtractResult()
        error = None
        try:
            sz.extract(targets=[i.filename for i in cands], factory=factory)
        except BookError:
            raise
        except Exception as e:                    # 체크섬 오류, 깨진 압축 데이터 등 - 받은 데까지는 쓴다
            error = e
        finally:
            for out in factory.outs.values():
                if out.path is not None:
                    try:
                        out.f.close()
                    except OSError:
                        pass

        got = []
        for out in factory.outs.values():
            label = out.name.lstrip("/")
            if out.written == 0 and not out.done:
                if out.path:
                    temp_store_discard(out.path)
                continue
            damaged = not out.done or out.written < expected.get(out.name, expected.get(label, 0))
            if out.path is None:
                got.append(ExtractedImage(label=label, data=out.f.getvalue(), damaged=damaged))
            else:
                got.append(ExtractedImage(label=label, path=out.path, damaged=damaged))
        received = {it.label for it in got}
        missing = [i.filename for i in cands if i.filename.lstrip("/") not in received]
        for name in missing:
            results.warnings.append(f"{name}: 손상되어 읽지 못했습니다. 목록에서 뺐습니다.")
        if error is not None and not missing and not any(it.damaged for it in got):
            results.warnings.append(f"7z를 푸는 중 오류가 있었습니다: {error}")
        got.sort(key=lambda it: path_key(it.label))
        results.extend(got)
        return results


def temp_store_discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
