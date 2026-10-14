"""
이미지를 클립보드로 복사 - 웹 브라우저의 "이미지 복사"처럼, 붙여 넣는 프로그램(그림판, 워드, 카카오톡, 포토샵 등)이
그림으로 받을 수 있게 클립보드에 넣는다. tkinter의 클립보드는 글자만 다룰 수 있어서 운영체제 기능을 직접 쓴다.

- 윈도우: 두 가지 형식을 함께 넣는다(브라우저와 같은 방식).
  1) CF_DIB - 윈도우 표준 그림 형식(거의 모든 프로그램이 받음). 투명한 부분은 흰 바탕으로 합친다.
  2) "PNG" - PNG 파일 그대로(투명도 유지). 이 형식을 아는 프로그램(오피스, 브라우저, 포토샵 등)은 이쪽을 쓴다.
- 그 밖(리눅스 등, 개발/시험용): xclip 또는 wl-copy가 있으면 PNG로 넣는다.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import time
from typing import List, Tuple

CF_DIB = 8
GMEM_MOVEABLE = 0x0002


class ClipboardError(Exception):
    """사용자에게 그대로 보여 줄 사유(한국어)."""


def _flatten_rgb(im):
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return im.convert("RGB")


def encode(im) -> Tuple[bytes, bytes]:
    """(CF_DIB 바이트, PNG 바이트). DIB는 BMP 파일에서 앞의 14바이트(파일 머리)를 뗀 것이다."""
    bmp = io.BytesIO()
    _flatten_rgb(im).save(bmp, "BMP")
    png = io.BytesIO()
    keep = im if im.mode in ("1", "L", "LA", "P", "RGB", "RGBA") else im.convert("RGBA" if "A" in im.getbands() else "RGB")
    keep.save(png, "PNG", compress_level=1)          # 빠르게(클립보드용 - 무손실이라 화질은 같음)
    return bmp.getvalue()[14:], png.getvalue()


def _win_set(formats: List[Tuple[object, bytes]]) -> None:
    """formats: [(형식 번호 또는 등록할 형식 이름, 데이터), ...]를 한 번에 클립보드에 넣는다."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p

    for _ in range(20):                               # 다른 프로그램이 잠깐 클립보드를 쓰고 있으면 조금 기다렸다 다시
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise ClipboardError("클립보드를 열 수 없습니다(다른 프로그램이 사용 중). 잠시 후 다시 시도하세요.")
    try:
        if not user32.EmptyClipboard():
            raise ClipboardError("클립보드를 비우지 못했습니다.")
        for fmt, data in formats:
            if isinstance(fmt, str):
                fmt = user32.RegisterClipboardFormatW(fmt)
                if not fmt:
                    continue
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                raise ClipboardError("메모리가 부족해 클립보드에 넣지 못했습니다.")
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                kernel32.GlobalFree(handle)
                raise ClipboardError("메모리가 부족해 클립보드에 넣지 못했습니다.")
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(fmt, handle):  # 성공하면 메모리는 클립보드가 가진다(해제하면 안 됨)
                kernel32.GlobalFree(handle)
                raise ClipboardError("클립보드에 이미지를 넣지 못했습니다.")
    finally:
        user32.CloseClipboard()


def _other_set(png: bytes) -> None:
    for cmd in (["xclip", "-selection", "clipboard", "-t", "image/png", "-i"], ["wl-copy", "--type", "image/png"]):
        if shutil.which(cmd[0]):
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc.communicate(png, timeout=20)
            except (OSError, subprocess.SubprocessError) as e:
                raise ClipboardError(f"클립보드에 넣지 못했습니다: {e}")
            if proc.returncode == 0:
                return
    raise ClipboardError("이 운영체제에서는 이미지 복사를 지원하지 않습니다(xclip 또는 wl-copy 필요).")


def copy_image(im) -> None:
    """PIL 이미지를 클립보드에 그림으로 넣는다. 실패하면 ClipboardError."""
    try:
        dib, png = encode(im)
    except MemoryError:
        raise ClipboardError("이미지가 너무 커서 복사하지 못했습니다(메모리 부족).")
    if os.name == "nt":
        _win_set([(CF_DIB, dib), ("PNG", png)])
    else:
        _other_set(png)
