"""
메모리 정보 - 지금 컴퓨터에서 쓸 수 있는 여유 RAM이 얼마인지 알아낸다(추가 패키지 없이).
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional


def available_ram_bytes() -> Optional[int]:
    """사용 가능한 물리 메모리(바이트). 알아낼 수 없으면 None."""
    try:
        if sys.platform.startswith("win"):
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullAvailPhys)
            return None
        with open("/proc/meminfo", "r", encoding="ascii", errors="ignore") as f:   # 리눅스(개발/테스트용)
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None
