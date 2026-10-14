"""
버그 리포트 - 프로그램이 오류로 멈추거나 갑자기 꺼졌을 때 "그때 무슨 일이 있었는지"를 파일로 남기고 알려 준다.

남기는 것:
- 활동 기록 meltPDF_log.txt(%APPDATA%\\meltPDF\\logs - 보고서의 재료일 뿐 따로 찾을 필요 없음): 끌어다 놓기, 불러오기 작업의 시작/끝/중단, 목록 추가/삭제 등을 한 줄씩(activity_log.py).
- [설정] -> [버그 리포트 만들기]: 오류 창이 없던 문제도 지금 상태 + 최근 기록 + 지난번 기록으로 보고서를 만든다.
- 오류 보고서: 실행 파일(exe)이 있는 폴더에 meltpdf_버전_bug_report_yyyymmddHHMMSS.txt(예: meltpdf_0191_bug_report_20261014153012.txt).
  거기에 쓸 수 없을 때만 활동 기록 폴더. 오류가 나면 바로 만든다. 프로그램/윈도우/파이썬 버전, 그때의 상태(목록 장수,
  진행 중인 불러오기 수, 창 크기 등), 오류 내용(어느 코드에서 났는지), 최근 활동 기록 수백 줄.
  - 화면 쪽 오류(버튼, 끌어다 놓기 처리 등): 보고서를 만들고 오류 창으로 알린다(프로그램은 계속 동작).
  - 일꾼 스레드 오류: 보고서를 만들고 화면 스레드에서 알린다.
- 갑자기 꺼짐(파이썬 바깥의 충돌 - 메모리 접근 오류, Tcl/Tk 내부 오류 등): 그 순간 모든 스레드가 어디를 실행 중이었는지를
  meltPDF_fatal.txt에 남긴다(faulthandler). 다음에 켤 때 지난 기록에 정상 종료 표시가 없으면 지난 기록 + 이 내용으로
  보고서를 만들고 "지난번 실행이 비정상적으로 끝났습니다"라고 알린다(작업 관리자로 끈 경우도 여기에 해당).
- 화면 멈춤: 화면 스레드가 MAX_FREEZE초 넘게 응답하지 않으면 그때 모든 스레드의 실행 위치를 활동 기록에 남긴다
  (멈춘 채로 강제 종료하면 다음에 켤 때 위의 보고서에 들어간다).
보고서에는 파일 이름만 들어가고 전체 경로는 들어가지 않는다(오류 내용 안의 프로그램 코드 경로는 예외).
"""
from __future__ import annotations

import faulthandler
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from tkinter import messagebox
from typing import Callable, Optional

import activity_log
import ui_mailbox
from config import APP_NAME, APP_TITLE, APP_VERSION

FATAL_NAME = "meltPDF_fatal.txt"
MAX_FREEZE = 10.0           # 이 시간(초) 넘게 화면 스레드가 응답이 없으면 멈춤으로 보고 기록
BEAT_MS = 1000

_root = None
_state_fn: Optional[Callable[[], str]] = None
_fatal_file = None
_last_beat = time.monotonic()
_freeze_logged = False
_showing = False            # 오류 창을 여러 개 겹쳐 띄우지 않게


# ---------------------------------------------------------- 시작/끝
def start() -> None:
    """프로그램 맨 처음(창을 만들기 전)에 부른다: 활동 기록을 열고, 지난번 비정상 종료 흔적을 모아 두고, 충돌 기록을 켠다."""
    global _fatal_file
    activity_log.start(_env_lines())
    d = activity_log.log_dir()
    prev_fatal = ""
    if d is not None:
        fatal = d / FATAL_NAME
        try:
            if fatal.exists():
                prev_fatal = fatal.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pass
        try:
            _fatal_file = open(fatal, "w", encoding="utf-8")
            faulthandler.enable(file=_fatal_file, all_threads=True)
        except (OSError, RuntimeError, ValueError):
            _fatal_file = None
    _collect_previous(prev_fatal)
    _prune()
    sys.excepthook = _on_uncaught
    threading.excepthook = _on_thread_exception
    activity_log.log(f"프로그램 시작 (화면 스레드 id 0x{threading.get_ident():x})")


def attach(root, state_fn: Optional[Callable[[], str]] = None) -> None:
    """창을 만든 뒤에 부른다: 화면 콜백 오류 처리, 멈춤 감시, (있으면) 지난번 비정상 종료 알림."""
    global _root, _state_fn
    _root = root
    _state_fn = state_fn
    root.report_callback_exception = _on_tk_exception
    _beat()
    threading.Thread(target=_watchdog, name="멈춤감시", daemon=True).start()
    if _pending_previous_report is not None:
        root.after(800, _announce_previous)


def finish() -> None:
    """정상 종료 때(창을 닫은 뒤) 부른다."""
    activity_log.log("창 닫힘")
    try:
        faulthandler.disable()
        if _fatal_file is not None:
            _fatal_file.close()
            d = activity_log.log_dir()
            if d is not None:
                (d / FATAL_NAME).unlink(missing_ok=True)     # 정상 종료면 충돌 기록은 비어 있으므로 지운다
    except OSError:
        pass
    activity_log.finish()


# ---------------------------------------------------------- 보고서
def _env_lines():
    try:
        os_name = platform.platform()
    except Exception:
        os_name = sys.platform
    return [
        f"meltPDF v{APP_VERSION} 활동 기록 - 시작 {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"OS: {os_name} | 파이썬 {platform.python_version()} ({platform.architecture()[0]})"
        f" | exe: {'예' if getattr(sys, 'frozen', False) else '아니오'} | CPU {os.cpu_count()}개",
        "-" * 60,
    ]


def _state() -> str:
    if _state_fn is None:
        return "(상태 정보 없음)"
    try:
        return _state_fn()
    except Exception as e:
        return f"(상태를 읽지 못함: {e})"


def report_name(d: Path, when: Optional[float] = None) -> str:
    """보고서 파일 이름: 프로그램명_버전_bug_report_yyyymmddHHMMSS.txt (예: meltpdf_0191_bug_report_20261014153012.txt).
    프로그램명은 소문자, 버전은 점을 뺀 숫자. 같은 초에 이미 있으면 끝에 _2, _3 ...을 붙인다."""
    stem = f"{APP_NAME.lower()}_{APP_VERSION.replace('.', '')}_bug_report_{time.strftime('%Y%m%d%H%M%S', time.localtime(when))}"
    name, n = f"{stem}.txt", 2
    while (d / name).exists():
        name, n = f"{stem}_{n}.txt", n + 1
    return name


def report_dir() -> Optional[Path]:
    """버그 리포트를 만들 폴더: 실행 파일(exe, 개발 중에는 main.py)이 있는 폴더. 거기에 쓸 수 없을 때만(Program Files 등)
    활동 기록 폴더(%APPDATA%\\meltPDF\\logs) - 이때도 알림 창에 실제 위치를 보여 준다."""
    d = activity_log.app_dir()
    try:
        probe = d / f".{APP_NAME.lower()}_write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return d
    except OSError:
        return activity_log.log_dir()


def write_report(kind: str, detail: str, include_recent: bool = True, extra: str = "") -> Optional[Path]:
    """보고서 파일을 만들고 경로를 돌려준다(실패하면 None)."""
    d = report_dir()
    if d is None:
        return None
    name = report_name(d)
    parts = [f"meltPDF 버그 리포트 - {kind}", f"만든 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
    parts += _env_lines()[1:2]
    parts += ["", "[그때의 상태]", _state() if _root is not None else "(창이 뜨기 전)", "", "[내용]", detail.rstrip()]
    if extra:
        parts += ["", extra.rstrip()]
    if include_recent:
        parts += ["", f"[최근 활동 기록 (마지막 {activity_log.KEEP_LINES}줄까지)]"] + activity_log.recent()
    try:
        path = d / name
        path.write_text("\n".join(parts) + "\n", encoding="utf-8")
        activity_log.log(f"버그 리포트 저장: {name}")
        return path
    except OSError:
        return None


def make_report_now() -> None:
    """[설정]의 [버그 리포트 만들기]: 오류 창이 뜨지 않은 문제(이상한 동작, 느림 등)도 알릴 수 있게, 지금 상태와
    이번 실행의 최근 기록 + 지난번 실행의 기록으로 보고서를 실행 파일 위치에 만든다."""
    activity_log.log("[버그 리포트 만들기] 누름")
    extra = ""
    prev = activity_log.previous
    if prev is not None:
        try:
            lines = prev.read_text(encoding="utf-8", errors="replace").rstrip().splitlines()
            extra = "[지난번 실행의 활동 기록]\n" + "\n".join(lines[-3000:])
        except OSError:
            pass
    path = write_report("사용자가 만든 보고서", "[설정] -> [버그 리포트 만들기]로 만든 보고서입니다(오류가 나지 않은 상태).",
                        extra=extra)
    if path is None:
        messagebox.showerror(APP_TITLE, "버그 리포트를 만들지 못했습니다.")
        return
    if messagebox.askyesno(APP_TITLE, f"버그 리포트를 만들었습니다:\n{path}\n\n저장한 폴더를 열까요?"):
        open_folder(path)


def _prune(keep: int = 20) -> None:
    """오래된 버그 리포트는 지운다(최근 keep개만 둔다)."""
    d = report_dir()
    if d is None:
        return
    try:
        # 이 프로그램이 만든 이름(프로그램명_버전_bug_report_...)만, 만든 순서대로(실행 파일 폴더의 다른 파일은 건드리지 않음)
        reports = sorted(d.glob(f"{APP_NAME.lower()}_*_bug_report_*.txt"), key=lambda p: p.stat().st_mtime)
        for old in reports[:-keep]:
            old.unlink()
    except OSError:
        pass


def open_folder(path: Optional[Path]) -> None:
    """보고서가 있는 폴더를 연다(윈도우는 그 파일을 선택한 채로)."""
    if path is None:
        return
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError:
        pass


def _tell(title_line: str, path: Optional[Path]) -> None:
    """(화면 스레드) 알림 창: 보고서 위치를 알리고 폴더를 열지 묻는다."""
    global _showing
    if _showing:
        return
    _showing = True
    try:
        if path is None:
            messagebox.showerror(APP_TITLE, title_line + "\n\n(기록 파일을 만들지 못했습니다.)")
            return
        msg = (f"{title_line}\n\n그때의 기록을 버그 리포트로 저장했습니다:\n{path}\n\n"
               "이 파일을 보내 주시면 원인을 찾는 데 도움이 됩니다. 저장한 폴더를 열까요?")
        if messagebox.askyesno(APP_TITLE, msg, icon="warning"):
            open_folder(path)
    except Exception:
        pass
    finally:
        _showing = False


# ---------------------------------------------------------- 오류 잡기
def _on_tk_exception(exc, val, tb):
    text = "".join(traceback.format_exception(exc, val, tb))
    activity_log.log(f"화면 쪽 오류: {exc.__name__}: {val}")
    path = write_report("화면 쪽 오류(프로그램은 계속 동작)", text)
    _tell(f"예상치 못한 오류가 발생했습니다:\n{exc.__name__}: {val}", path)


def _on_thread_exception(args):
    if args.exc_type is SystemExit:
        return
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    name = getattr(args.thread, "name", "?")
    activity_log.log(f"스레드({name}) 오류: {args.exc_type.__name__}: {args.exc_value}")
    path = write_report(f"스레드({name}) 오류", text)
    if _root is not None:
        try:
            ui_mailbox.post(lambda: _tell(f"작업 중 예상치 못한 오류가 발생했습니다:\n{args.exc_type.__name__}: {args.exc_value}", path))
        except Exception:
            pass


def _on_uncaught(exc, val, tb):
    text = "".join(traceback.format_exception(exc, val, tb))
    activity_log.log(f"처리되지 않은 오류: {exc.__name__}: {val}")
    write_report("처리되지 않은 오류", text)
    try:
        sys.__excepthook__(exc, val, tb)       # exe(창 모드)에는 콘솔이 없어 출력할 곳이 없을 수 있다
    except Exception:
        pass


def report_startup_failure() -> Optional[Path]:
    """창을 띄우기도 전에 난 오류(except 블록 안에서 부름)."""
    text = traceback.format_exc()
    activity_log.log("시작 실패")
    path = write_report("프로그램 시작 실패", text)
    try:
        messagebox.showerror(APP_TITLE, f"프로그램을 시작하지 못했습니다.\n자세한 기록: {path}")
    except Exception:
        pass
    return path


def note_handled(what: str, exc: BaseException) -> None:
    """처리한 오류(프로그램은 정상 동작)라도 원인을 알 수 있게 활동 기록에 오류 위치까지 남긴다."""
    try:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
        activity_log.log(f"{what}: {type(exc).__name__}: {exc}\n    " + tb.replace("\n", "\n    "))
    except Exception:
        pass


# ---------------------------------------------------------- 지난번 비정상 종료
_pending_previous_report: Optional[Path] = None


def _collect_previous(prev_fatal: str) -> None:
    global _pending_previous_report
    prev = activity_log.previous
    if prev is None:
        return
    try:
        text = prev.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    lines = text.rstrip().splitlines()
    if not lines or lines[-1].strip() == activity_log.END_MARK:
        return
    detail = ("지난번 실행이 정상 종료 표시 없이 끝났습니다(오류로 갑자기 꺼졌거나, 응답이 없어 작업 관리자 등으로 끈 경우).\n"
              f"마지막 기록: {lines[-1]}")
    extra = "[충돌 순간 스레드별 실행 위치 (faulthandler)]\n" + (prev_fatal or "(기록 없음 - 강제 종료였거나 파이썬 바깥에서 기록하지 못한 충돌)")
    extra += "\n\n[지난번 활동 기록 전체]\n" + "\n".join(lines[-3000:])
    _pending_previous_report = write_report("지난번 실행의 비정상 종료", detail, include_recent=False, extra=extra)


def crash_notice_text(path: Optional[Path]) -> str:
    """다음 실행 때 띄우는 알림 글(사용자 지정 형식): 크래시 감지. [보고서 파일 이름]이 생성되었습니다. + 파일 위치."""
    if path is None:
        return "크래시 감지. 버그 리포트를 만들지 못했습니다."
    return f"크래시 감지. {path.name}이 생성되었습니다.\n\n위치: {path.parent}\n\n이 폴더를 열까요?"


def _announce_previous():
    """(화면 스레드) 지난번 실행이 비정상 종료였을 때: 보고서 이름과 위치를 알리고 폴더를 열지 묻는다."""
    global _showing
    path = _pending_previous_report
    activity_log.log("지난번 비정상 종료 알림 표시")
    _showing = True
    try:
        if path is None:
            messagebox.showwarning(APP_TITLE, crash_notice_text(None))
        elif messagebox.askyesno(APP_TITLE, crash_notice_text(path), icon="warning"):
            open_folder(path)
    except Exception:
        pass
    finally:
        _showing = False


# ---------------------------------------------------------- 화면 멈춤 감시
def _beat():
    global _last_beat
    _last_beat = time.monotonic()
    try:
        _root.after(BEAT_MS, _beat)
    except Exception:
        pass


def _watchdog():
    global _freeze_logged
    while True:
        time.sleep(2.0)
        gap = time.monotonic() - _last_beat
        if gap > MAX_FREEZE and not _freeze_logged:
            _freeze_logged = True
            activity_log.log(f"화면이 {gap:.0f}초째 응답 없음 - 스레드별 실행 위치:\n" + _all_stacks())
        elif gap <= MAX_FREEZE and _freeze_logged:
            _freeze_logged = False
            activity_log.log("화면 응답 돌아옴")


def _all_stacks() -> str:
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in sys._current_frames().items():
        if names.get(ident) == "멈춤감시":
            continue
        out.append(f"  --- 스레드 {names.get(ident, ident)}")
        out.extend("    " + ln for ln in "".join(traceback.format_stack(frame)).rstrip().splitlines())
    return "\n".join(out)
