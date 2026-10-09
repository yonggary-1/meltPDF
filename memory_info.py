"""
메모리 정보 - 지금 컴퓨터의 여유 RAM, 전체 RAM, 이 프로그램이 쓰는 RAM을 알아낸다(추가 패키지 없이).
여유 RAM은 불러온 이미지를 메모리에 둘지 정하는 데(storage_policy), 나머지는 하단 상태바의 메모리 미터(ram_meter)가 쓴다.
알아낼 수 없으면 None을 돌려주고 호출하는 쪽이 알아서 건너뛴다.
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional


def _windows_status():
    """윈도우의 GlobalMemoryStatusEx 결과(구조체). 실패하면 None."""
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
        return stat
    return None


def _meminfo_kb(key: str) -> Optional[int]:
    """리눅스(개발/테스트용) /proc/meminfo의 항목(KB)."""
    with open("/proc/meminfo", "r", encoding="ascii", errors="ignore") as f:
        for line in f:
            if line.startswith(key + ":"):
                return int(line.split()[1])
    return None


def available_ram_bytes() -> Optional[int]:
    """사용 가능한 물리 메모리(바이트). 알아낼 수 없으면 None."""
    try:
        if sys.platform.startswith("win"):
            stat = _windows_status()
            return int(stat.ullAvailPhys) if stat else None
        kb = _meminfo_kb("MemAvailable")
        return kb * 1024 if kb is not None else None
    except Exception:
        return None


def total_ram_bytes() -> Optional[int]:
    """컴퓨터에 설치된 물리 메모리 전체(바이트). 알아낼 수 없으면 None."""
    try:
        if sys.platform.startswith("win"):
            stat = _windows_status()
            return int(stat.ullTotalPhys) if stat else None
        kb = _meminfo_kb("MemTotal")
        return kb * 1024 if kb is not None else None
    except Exception:
        return None


def process_ram_bytes() -> Optional[int]:
    """이 프로그램이 지금 실제로 쓰는 물리 메모리(바이트, 작업 집합/상주 메모리). 알아낼 수 없으면 None."""
    try:
        if sys.platform.startswith("win"):
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE          # 64비트에서 핸들이 잘리지 않게 형을 지정한다
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return int(counters.WorkingSetSize)
            return None
        import os
        with open("/proc/self/statm", "r", encoding="ascii") as f:
            resident_pages = int(f.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        return None
