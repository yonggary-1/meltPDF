"""
저장 위치 결정 - 압축/책 파일에서 꺼낸 이미지를 메모리(RAM)에 둘지 디스크 임시 폴더에 둘지 정한다.

기본은 RAM이다. 설정이 "ask"(기본)이면, 이미 목록이 들고 있는 양 + 이번에 꺼낼 양이 한도를 넘을 때만
사용자에게 "디스크를 쓸까요?"라고 묻는다.
  한도 = 설정의 메모리 한도(GB)가 있으면 그 값, 0(자동)이면 "지금 남은 메모리의 절반".
  남은 메모리를 알 수 없으면 2GB로 본다.
화면(대화상자)은 모르고, 묻는 동작은 ask_fn으로 받아서 테스트할 수 있게 했다.
"""
from __future__ import annotations

from typing import Callable, Optional

import memory_info
from settings import STORAGE_DISK, STORAGE_RAM, Settings

GB = 1024 ** 3
FALLBACK_LIMIT = 2 * GB

RAM = "ram"
DISK = "disk"

# ask_fn(이번에 꺼낼 바이트, 한도 바이트) -> True면 디스크 사용, False면 불러오기 취소
AskFn = Callable[[int, int], bool]


def ram_limit_bytes(settings: Settings) -> int:
    configured = float(settings.get("ram_limit_gb") or 0)
    if configured > 0:
        return int(configured * GB)
    available = memory_info.available_ram_bytes()
    return available // 2 if available else FALLBACK_LIMIT


def choose(estimate_bytes: int, held_bytes: int, settings: Settings, ask_fn: AskFn) -> Optional[str]:
    """RAM / DISK 중 하나를 돌려준다. 사용자가 불러오기를 취소하면 None."""
    mode = settings.get("storage_mode")
    if mode == STORAGE_DISK:
        return DISK
    if mode == STORAGE_RAM:
        return RAM
    limit = ram_limit_bytes(settings)
    if held_bytes + estimate_bytes <= limit:
        return RAM
    return DISK if ask_fn(estimate_bytes, limit) else None
