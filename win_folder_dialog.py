"""
윈도우 폴더 선택 창에 체크 상자 넣기 - 윈도우 표준 파일/폴더 선택 창(IFileOpenDialog, 폴더 고르기 모드)을 직접 띄우고,
IFileDialogCustomize로 [폴더 선택] 버튼 옆에 체크 상자를 붙인다(MakeProminent: 확인/취소 버튼 줄에 놓임).
tkinter의 askdirectory는 같은 창을 쓰지만 컨트롤을 넣는 길을 열어 주지 않아서, COM 인터페이스를 ctypes로 직접 부른다
(추가 패키지 없음). 윈도우가 아니거나 어떤 이유로든 실패하면 예외를 내고, 부르는 쪽(folder_pick.py)이 예전 방식으로 대신한다.

인터페이스 메서드 번호(vtable 순서)는 Windows SDK의 shobjidl_core.h를 따른다.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import POINTER, byref, c_int, c_long, c_uint, c_ulong, c_void_p, c_wchar_p
from typing import Optional, Tuple

if os.name == "nt":
    from ctypes import WINFUNCTYPE as _FUNCTYPE
else:                                                   # 윈도우가 아니면 쓰지 않는다(시험용으로 모듈만 읽힘)
    from ctypes import CFUNCTYPE as _FUNCTYPE


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        h = text.strip("{}").replace("-", "")
        self.Data1 = int(h[0:8], 16)
        self.Data2 = int(h[8:12], 16)
        self.Data3 = int(h[12:16], 16)
        for i in range(8):
            self.Data4[i] = int(h[16 + 2 * i:18 + 2 * i], 16)


CLSID_FileOpenDialog = "DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"
IID_IFileOpenDialog = "D57C7288-D4AD-4768-BE02-9D969532D960"
IID_IFileDialogCustomize = "E6FDD21A-163F-4975-9C8C-A69F1BA37034"

CLSCTX_INPROC_SERVER = 0x1
COINIT_APARTMENTTHREADED = 0x2
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000 - (1 << 32)              # c_int로 넘길 수 있게 음수로
HRESULT_CANCELLED = 0x800704C7 - (1 << 32)              # 사용자가 [취소]를 누름

# vtable 번호 (IUnknown 0~2, IModalWindow::Show 3, 그 뒤 IFileDialog)
_QI, _RELEASE = 0, 2
_SHOW, _SET_OPTIONS, _GET_OPTIONS, _SET_TITLE, _GET_RESULT = 3, 9, 10, 17, 20
_ADD_CHECK, _GET_CHECK, _MAKE_PROMINENT = 8, 17, 28      # IFileDialogCustomize
_GET_DISPLAY_NAME = 5                                    # IShellItem
CHECK_ID = 1001


def _method(ptr: c_void_p, index: int, *argtypes):
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    return _FUNCTYPE(c_long, c_void_p, *argtypes)(vtbl[index])


def _check(hr: int, what: str) -> None:
    if hr < 0:
        raise OSError(f"{what} 실패 (HRESULT 0x{hr & 0xFFFFFFFF:08X})")


def _release(ptr: Optional[c_void_p]) -> None:
    if ptr:
        try:
            _method(ptr, _RELEASE)(ptr)
        except Exception:
            pass


def pick_folder(owner_hwnd: int, title: str, check_label: str, checked: bool) -> Tuple[Optional[str], bool]:
    """폴더 선택 창을 띄운다. (고른 폴더 경로 또는 취소면 None, 체크 상자 상태)를 돌려준다. 띄우지 못하면 OSError."""
    if os.name != "nt":
        raise OSError("윈도우가 아님")
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [c_void_p, c_uint]
    ole32.CoInitializeEx.restype = c_long
    ole32.CoCreateInstance.argtypes = [POINTER(_GUID), c_void_p, c_uint, POINTER(_GUID), POINTER(c_void_p)]
    ole32.CoCreateInstance.restype = c_long
    ole32.CoTaskMemFree.argtypes = [c_void_p]
    ole32.CoTaskMemFree.restype = None
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)   # 이미 초기화돼 있으면 S_FALSE/RPC_E_CHANGED_MODE - 그대로 진행

    dialog = c_void_p()
    custom = c_void_p()
    item = c_void_p()
    try:
        _check(ole32.CoCreateInstance(byref(_GUID(CLSID_FileOpenDialog)), None, CLSCTX_INPROC_SERVER,
                                      byref(_GUID(IID_IFileOpenDialog)), byref(dialog)), "CoCreateInstance")
        opts = c_uint(0)
        _check(_method(dialog, _GET_OPTIONS, POINTER(c_uint))(dialog, byref(opts)), "GetOptions")
        _check(_method(dialog, _SET_OPTIONS, c_uint)(dialog, opts.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM
                                                     | FOS_PATHMUSTEXIST), "SetOptions")
        _method(dialog, _SET_TITLE, c_wchar_p)(dialog, title)

        _check(_method(dialog, _QI, POINTER(_GUID), POINTER(c_void_p))(
            dialog, byref(_GUID(IID_IFileDialogCustomize)), byref(custom)), "QueryInterface(IFileDialogCustomize)")
        _check(_method(custom, _ADD_CHECK, c_uint, c_wchar_p, c_int)(custom, CHECK_ID, check_label, 1 if checked else 0),
               "AddCheckButton")
        _method(custom, _MAKE_PROMINENT, c_uint)(custom, CHECK_ID)   # [폴더 선택]/[취소] 버튼 줄에 놓는다(실패해도 아래쪽에 보임)

        hr = _method(dialog, _SHOW, c_void_p)(dialog, c_void_p(owner_hwnd) if owner_hwnd else None)
        state = c_int(1 if checked else 0)
        _method(custom, _GET_CHECK, c_uint, POINTER(c_int))(custom, CHECK_ID, byref(state))
        if hr == HRESULT_CANCELLED:
            return None, bool(state.value)
        _check(hr, "Show")
        _check(_method(dialog, _GET_RESULT, POINTER(c_void_p))(dialog, byref(item)), "GetResult")
        name = c_void_p()
        _check(_method(item, _GET_DISPLAY_NAME, c_int, POINTER(c_void_p))(item, SIGDN_FILESYSPATH, byref(name)),
               "GetDisplayName")
        try:
            path = ctypes.wstring_at(name)
        finally:
            ole32.CoTaskMemFree(name)
        return path, bool(state.value)
    finally:
        _release(item)
        _release(custom)
        _release(dialog)
