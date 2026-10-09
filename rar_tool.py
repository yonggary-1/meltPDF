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

예외(메모리 방식, v0.10.2): UnRAR는 `p` 명령으로 파일 내용을 표준 출력에 차례로 내보낼 수 있다. 그러면 디스크에 아무것도
쓰지 않고(임시 폴더 없음) 한 번의 실행으로 전부 받을 수 있어서, 메모리에 두기로 한 경우에는 open_stream으로 받는다(archive_rar가
크기/체크섬으로 검증하고, 맞지 않으면 위의 디스크 방식으로 되돌아간다).
"""
from __future__ import annotations

import locale
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

FAIL_HINT = ("파일이 손상되었거나 다운로드가 끝나지 않았을 수 있습니다. 다른 프로그램(WinRAR, 7-Zip)으로도 풀리지 않는지 확인해 보세요.\n"
             "이 창의 내용을 그대로 알려 주시면 원인을 찾는 데 도움이 됩니다.")

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
        return [exe, "x", "-y", "-idq", "-p-", "-o+", "-kb", archive, dest + os.sep]   # -kb: 깨진 파일도 풀린 데까지 남겨 둔다
    if kind == "7z":
        return [exe, "x", "-y", "-bso0", "-bsp0", f"-o{dest}", archive]
    if kind == "unar":
        return [exe, "-q", "-D", "-f", "-o", dest, archive]
    return [exe, "-xf", archive, "-C", dest]          # bsdtar


def open_stream(exe: str, archive: str) -> subprocess.Popen:
    """UnRAR의 `p` 명령으로 압축 안 파일들의 내용을 표준 출력으로 차례로(압축 파일에 저장된 순서, 폴더 항목 제외) 내보내게 한다.
    출력에는 파일 경계가 없으므로 부르는 쪽이 목차의 크기로 잘라 쓴다. -inul: 메시지를 전혀 내지 않음(내용만 출력)."""
    return subprocess.Popen([exe, "p", "-inul", "-p-", "-y", archive], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **_popen_flags())


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


def bundled_unrar_status() -> str:
    """프로그램에 같이 들어 있어야 하는 UnRAR.exe가 실제로 있는지 한 줄로 알려 준다(오류 안내에 붙임).
    없으면 설치 환경 문제(백신이 지움, 빌드에서 빠짐 등)를 의심할 수 있다."""
    if not IS_WINDOWS:
        return ""
    paths = []
    for base in (getattr(sys, "_MEIPASS", None), Path(__file__).resolve().parent):
        if base:
            p = Path(base) / "tools" / "UnRAR.exe"
            if str(p) not in paths:
                paths.append(str(p))
    parts = []
    for p in paths:
        try:
            parts.append(f"{p} - " + (f"있음 ({os.path.getsize(p):,}바이트)" if os.path.isfile(p) else "없음"))
        except OSError as e:
            parts.append(f"{p} - 확인 실패 ({e})")
    return "내장 UnRAR.exe 위치: " + " / ".join(parts)


def _decode(raw: bytes) -> str:
    """도구가 출력한 글자를 읽을 수 있게 바꾼다. 윈도우 도구(tar.exe 등)는 UTF-8이 아니라 시스템 문자 코드(한국어 윈도우는 cp949)로 내보낸다."""
    for enc in ("utf-8", "mbcs" if os.name == "nt" else (locale.getpreferredencoding(False) or "utf-8")):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", "replace")


# 일부 파일만 문제가 있어도 나머지는 풀리는 종료 코드 - 풀린 파일이 하나라도 있으면 그 결과를 쓴다.
#   unrar: 1 = 경고, 3 = 손상된 파일(체크섬 오류)이 있음 (-kb 옵션으로 깨진 파일도 풀린 데까지 남긴다)
#   7z:    1 = 경고
PARTIAL_OK = {"unrar": (1, 3), "7z": (1,)}


def _run_tool(kind: str, exe: str, archive: str, dest: str, on_count: Callable[[int], None]) -> Tuple[int, str, int]:
    """도구 하나를 실행한다. (종료 코드, 도구가 낸 마지막 메시지, 풀린 파일 수)를 돌려준다. 실행 자체를 못 하면 종료 코드 -1."""
    _reset_dir(dest)
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen(_command(kind, exe, archive, dest), stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=subprocess.STDOUT, **_popen_flags())
        except OSError as e:
            return -1, f"실행하지 못함 ({e})", 0
        while True:
            try:
                proc.wait(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                on_count(_count_files(dest))
        count = _count_files(dest)
        on_count(count)
        out.seek(0)
        lines = [ln.strip() for ln in _decode(out.read()).splitlines() if ln.strip()]
        detail = " / ".join(lines[-2:])[:300] if lines else "출력 없음"
        return proc.returncode, detail, count


def _ascii_alias(archive: str, folder: str) -> Optional[str]:
    """일본어/중국어 등이 든 경로를 제대로 못 받는 도구(윈도우 tar.exe 등)를 위해, 같은 파일을 영문 이름으로 가리키게 한다.
    하드링크(같은 드라이브면 복사 없음) -> 복사 순서로 시도하고, 안 되면 None."""
    alias = os.path.join(folder, "archive.rar")
    for attempt in (os.link, shutil.copyfile):
        try:
            attempt(archive, alias)
            return alias
        except OSError:
            continue
    return None


def extract_all(archive: str, dest: str, on_count: Callable[[int], None],
                tools: Optional[List[Tool]] = None) -> str:
    """archive를 dest 폴더에 전부 푼다. on_count(지금까지 풀린 파일 수)를 주기적으로 부른다.
    도구가 실패하면 다음 도구로 다시 시도한다. 경로에 영문이 아닌 글자가 있어서 실패한 경우에는 영문 이름의 같은 파일로
    한 번 더 시도한다. 전부 실패하면 시도한 도구마다의 실패 이유를 담아 BookError를 낸다.
    돌려주는 값: 정상이면 "", 일부 파일에 문제가 있었지만 나머지는 풀렸으면 그 사실을 알리는 문장(경고)."""
    tools = find_tools() if tools is None else tools
    if not tools:
        raise BookError(INSTALL_HINT)
    failures: List[str] = []
    alias_dir: Optional[str] = None
    alias_path: Optional[str] = None

    def attempt(kind: str, label: str, exe: str, path: str) -> Optional[str]:
        rc, detail, count = _run_tool(kind, exe, path, dest, on_count)
        if rc == 0:
            return ""
        if rc in PARTIAL_OK.get(kind, ()) and count > 0:
            return (f"압축 파일의 일부에 문제가 있었습니다({label} 종료 코드 {rc}: {detail}). "
                    f"풀린 {count}개 파일을 사용합니다.")
        failures.append(f"{label}: " + ("" if rc < 0 else f"종료 코드 {rc}: ") + detail)
        return None

    try:
        for kind, exe in tools:
            name = Path(exe).name
            done = attempt(kind, name, exe, archive)
            if done is not None:
                return done
            if not archive.isascii():
                if alias_dir is None:
                    alias_dir = tempfile.mkdtemp(prefix="meltPDF_arc_")
                    alias_path = _ascii_alias(archive, alias_dir)
                if alias_path:
                    done = attempt(kind, f"{name}(영문 이름 사본)", exe, alias_path)
                    if done is not None:
                        return done
    finally:
        if alias_dir:
            shutil.rmtree(alias_dir, ignore_errors=True)
    status = bundled_unrar_status()
    raise BookError("rar 압축을 풀지 못했습니다. 시도한 도구와 실패 이유:\n  " + "\n  ".join(failures)
                    + ("\n\n" + status if status else "") + "\n\n" + FAIL_HINT)
