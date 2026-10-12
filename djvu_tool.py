"""
DjVu 풀기 도구 찾기/실행 - djvu의 쪽은 djvu 전용 압축(JB2, IW44)이라 파이썬으로 풀 방법이 마땅치 않아서, DjVuLibre의
ddjvu(쪽을 그림으로 풀기)와 djvused(쪽 수, 서지 정보 읽기)를 exe에 같이 넣어 두고 그것에 맡긴다.
출처, 라이선스(GPL-2.0 이상), 만든 방법은 tools/README.md와 THIRD_PARTY_NOTICES.md.

찾는 순서: 1) 프로그램에 같이 들어 있는 tools/ddjvu.exe, tools/djvused.exe (윈도우) 2) exe와 같은 폴더(또는 tools 폴더)에
사용자가 둔 것 3) 설치된 DjVuLibre(Program Files) 4) PATH의 ddjvu/djvused (리눅스 등).

윈도우 경로 문제: 이 도구들은 명령줄을 시스템 문자 코드(한국어 윈도우는 cp949)로 받는다. 그 문자 코드에 없는 글자(예: 일본어)가
든 경로는 깨지므로, 그런 경우에만 파일을 임시 폴더에 영어 이름으로 복사해서 넘긴다(input_path).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import temp_store
from book_common import BookError

IS_WINDOWS = os.name == "nt"
MISSING_HINT = ("djvu를 열려면 DjVuLibre의 ddjvu/djvused가 필요한데, 프로그램에 들어 있는 것을 찾지 못했습니다.\n"
                "DjVuLibre(https://djvu.sourceforge.net)를 설치하거나 ddjvu.exe와 djvused.exe를 이 프로그램과 같은 폴더에 넣어 주세요.")


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _find(name: str) -> Optional[str]:
    exe = name + ".exe" if IS_WINDOWS else name
    places: List[Path] = []
    for base in (getattr(sys, "_MEIPASS", None), Path(__file__).resolve().parent):
        if base:
            places.append(Path(base) / "tools" / exe)
    here = _app_dir()
    places += [here / exe, here / "tools" / exe]
    if IS_WINDOWS:
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            v = os.environ.get(var)
            if v:
                places.append(Path(v) / "DjVuLibre" / exe)
    for p in places:
        if p.is_file() and (IS_WINDOWS or os.access(p, os.X_OK)):
            return str(p)
    return shutil.which(name)


def find_tools() -> Tuple[str, str]:
    """(ddjvu, djvused) 실행 파일 경로. 없으면 BookError."""
    ddjvu, djvused = _find("ddjvu"), _find("djvused")
    if not ddjvu or not djvused:
        raise BookError(MISSING_HINT)
    return ddjvu, djvused


def popen_flags() -> dict:
    if IS_WINDOWS:                                       # 창 없는 프로그램에서 검은 콘솔 창이 번쩍이지 않게
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _ansi_ok(path: str) -> bool:
    if not IS_WINDOWS:
        return True
    try:
        path.encode("mbcs", "strict")
        return True
    except UnicodeError:
        return False


def input_path(path: str) -> Tuple[str, Optional[str]]:
    """도구에 넘길 경로와, 임시 복사본을 만들었으면 그 경로(다 쓰고 지울 것)."""
    path = os.path.abspath(path)
    if _ansi_ok(path):
        return path, None
    copy = temp_store.new_path(".djvu")
    if not _ansi_ok(copy):
        raise BookError("파일 경로에 이 컴퓨터의 문자 코드로 나타낼 수 없는 글자가 있어 djvu를 열 수 없습니다. "
                        "파일 이름을 바꾸거나 다른 폴더로 옮겨 보세요.")
    try:
        shutil.copyfile(path, copy)
    except OSError as e:
        raise BookError(f"djvu 파일을 임시 폴더로 복사하지 못했습니다: {e}")
    return copy, copy


def run_djvused(djvused: str, path: str, script: str, timeout: int = 120) -> str:
    """djvused로 명령(script)을 실행하고 출력(UTF-8)을 돌려준다."""
    try:
        r = subprocess.run([djvused, "-u", path, "-e", script], stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=timeout, **popen_flags())
    except (OSError, subprocess.SubprocessError) as e:
        raise BookError(f"djvused를 실행하지 못했습니다: {e}")
    if r.returncode != 0:
        lines = [l.strip(" *\t") for l in r.stderr.decode("utf-8", "replace").splitlines() if l.strip(" *\t")]
        detail = f"\n(djvused: {lines[0][:200]})" if lines else ""
        raise BookError(f"djvu 파일이 손상되었거나 djvu 형식이 아닙니다.{detail}")
    return r.stdout.decode("utf-8-sig", "replace").replace("\r\n", "\n")


def open_pages(ddjvu: str, path: str, first: int, last: int, err_file) -> subprocess.Popen:
    """first~last쪽을 원래 해상도 그대로(크기 지정 없음) 풀어 PNM 그림을 차례로 표준 출력에 내보내게 한다."""
    return subprocess.Popen([ddjvu, "-format=pnm", f"-page={first}-{last}", path, "-"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=err_file, **popen_flags())
