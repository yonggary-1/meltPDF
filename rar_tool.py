"""
RAR 풀기 도구 찾기/실행 - 파이썬으로 RAR 압축을 직접 푸는 라이브러리가 없어서, 공식 UnRAR(RARLAB)을
exe에 같이 넣어 두고(tools/UnRAR.exe - 출처와 라이선스는 tools/README.md, THIRD_PARTY_NOTICES.md)
그것에 한 번 맡겨 임시 폴더에 전부 푼다. 컴퓨터에 설치된 다른 도구는 예비로만 쓴다.

찾는 순서(앞에 있는 게 우선, 실패하면 다음 도구로 다시 시도):
  1) 프로그램에 같이 들어 있는 tools/UnRAR.exe (윈도우)
  2) exe와 같은 폴더(또는 그 안의 tools 폴더)에 사용자가 직접 둔 UnRAR.exe / 7z.exe
  3) 설치된 WinRAR의 UnRAR.exe, 설치된 7-Zip의 7z.exe
  4) PATH에 있는 unrar, 7z/7zz, unar, bsdtar (리눅스/맥 등)
  5) 윈도우 기본 tar.exe (libarchive 기반 - 압축을 연속(solid)으로 만든 rar는 못 풀 수 있어 마지막 순서)
어느 것도 없으면 BookError로 설치 방법을 안내한다.

한 번에 전부 풀고 나서 이미지를 골라 쓰는 이유: 파일 하나씩 풀면 연속(solid) 압축에서는 앞의 파일들을
매번 다시 풀어야 해서 극도로 느려진다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from book_common import BookError

# (종류, 실행 파일 경로)
Tool = Tuple[str, str]

INSTALL_HINT = ("rar/cbr을 열려면 압축 해제 도구가 필요한데, 프로그램에 들어 있는 UnRAR.exe를 쓸 수 없었습니다.\n"
                "7-Zip(무료, https://7-zip.org)을 설치하거나, 공식 UnRAR.exe를 이 프로그램과 같은 폴더에 넣어 주세요.\n"
                "(WinRAR가 설치되어 있으면 그것도 자동으로 사용합니다.)")

IS_WINDOWS = os.name == "nt"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _program_dirs() -> List[Path]:
    dirs = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(var)
        if v and Path(v) not in dirs:
            dirs.append(Path(v))
    return dirs


def _is_bsdtar(exe: str) -> bool:
    """tar가 libarchive(bsdtar)인지 확인한다 - 리눅스의 GNU tar는 rar를 못 읽는다."""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                             **_popen_flags()).stdout.lower()
    except Exception:
        return False
    return "bsdtar" in out or "libarchive" in out


def find_tools() -> List[Tool]:
    found: List[Tool] = []
    seen = set()

    def add(kind: str, exe: Optional[str]):
        if not exe or not os.path.isfile(exe):
            return
        key = os.path.normcase(os.path.abspath(exe))
        if key in seen:
            return
        seen.add(key)
        found.append((kind, exe))

    if IS_WINDOWS:                      # 1) 프로그램에 같이 들어 있는 UnRAR (PyInstaller exe 안에서는 _MEIPASS에 풀림)
        for base in (getattr(sys, "_MEIPASS", None), Path(__file__).resolve().parent):
            if base:
                add("unrar", str(Path(base) / "tools" / "UnRAR.exe"))
    here = _app_dir()
    for folder in (here, here / "tools"):
        for name in ("UnRAR.exe", "unrar.exe"):
            add("unrar", str(folder / name))
        add("7z", str(folder / "7z.exe"))
    for pf in _program_dirs():
        add("unrar", str(pf / "WinRAR" / "UnRAR.exe"))
        add("7z", str(pf / "7-Zip" / "7z.exe"))
    for name in ("unrar", "UnRAR"):
        add("unrar", shutil.which(name))
    for name in ("7z", "7zz"):     # 7za(단독 실행판)는 rar를 읽지 못해서 뺀다
        add("7z", shutil.which(name))
    add("unar", shutil.which("unar"))
    bsd = shutil.which("bsdtar")
    if bsd:
        add("bsdtar", bsd)
    sysroot = os.environ.get("SystemRoot")
    if sysroot:
        win_tar = str(Path(sysroot) / "System32" / "tar.exe")
        if os.path.isfile(win_tar) and _is_bsdtar(win_tar):
            add("bsdtar", win_tar)
    # 사용하기 좋은 순서(unrar > 7z > unar > bsdtar)를 지키되, 같은 종류 안에서는 찾은 순서를 유지한다
    rank = {"unrar": 0, "7z": 1, "unar": 2, "bsdtar": 3}
    return sorted(found, key=lambda t: rank[t[0]])


def _command(kind: str, exe: str, archive: str, dest: str) -> List[str]:
    if kind == "unrar":
        return [exe, "x", "-y", "-idq", "-p-", "-o+", archive, dest + os.sep]
    if kind == "7z":
        return [exe, "x", "-y", "-bso0", "-bsp0", f"-o{dest}", archive]
    if kind == "unar":
        return [exe, "-q", "-D", "-f", "-o", dest, archive]
    return [exe, "-xf", archive, "-C", dest]          # bsdtar


def _popen_flags() -> dict:
    if os.name == "nt":                                 # 창 없는 프로그램에서 검은 콘솔 창이 번쩍이지 않게
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _count_files(folder: str) -> int:
    n = 0
    for _root, _dirs, files in os.walk(folder):
        n += len(files)
    return n


def _reset_dir(folder: str) -> None:
    for entry in os.listdir(folder):
        p = os.path.join(folder, entry)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass


def extract_all(archive: str, dest: str, on_count: Callable[[int], None],
                tools: Optional[List[Tool]] = None) -> None:
    """archive를 dest 폴더에 전부 푼다. on_count(지금까지 풀린 파일 수)를 주기적으로 부른다.
    도구가 실패하면 다음 도구로 다시 시도하고, 전부 실패하면 BookError."""
    tools = find_tools() if tools is None else tools
    if not tools:
        raise BookError(INSTALL_HINT)
    last_error = ""
    for kind, exe in tools:
        _reset_dir(dest)
        with tempfile.TemporaryFile() as err:
            try:
                proc = subprocess.Popen(_command(kind, exe, archive, dest), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=err, **_popen_flags())
            except OSError as e:
                last_error = f"{Path(exe).name}: {e}"
                continue
            while True:
                try:
                    proc.wait(timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    on_count(_count_files(dest))
            on_count(_count_files(dest))
            if proc.returncode == 0:
                return
            err.seek(0)
            msg = err.read().decode("utf-8", "replace").strip().splitlines()
            last_error = f"{Path(exe).name}: " + (msg[-1] if msg else f"종료 코드 {proc.returncode}")
    raise BookError("rar 압축을 풀지 못했습니다 (" + last_error + ")\n\n" + INSTALL_HINT)
