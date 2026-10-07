"""
사용자 설정 저장 - 작은 JSON 파일 하나(윈도우: %APPDATA%\\Image2PDF\\settings.json).
읽기/쓰기에 실패해도 프로그램은 기본값으로 계속 동작해야 하므로 모든 입출력은 조용히 실패한다.
설정 화면은 settings_dialog.py, 설정값을 실제로 쓰는 곳은 storage_policy.py 등 각 기능 파일이다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# 압축/책 파일에서 꺼낸 이미지를 어디에 두는가
STORAGE_ASK = "ask"     # 메모리에 두되, 너무 크면 물어본다 (기본)
STORAGE_RAM = "ram"     # 크기와 상관없이 메모리만 쓴다 (묻지 않음 - 메모리가 모자라면 느려지거나 멈출 수 있음)
STORAGE_DISK = "disk"   # 항상 디스크 임시 폴더를 쓴다

DEFAULTS: Dict[str, Any] = {
    "storage_mode": STORAGE_ASK,
    "ram_limit_gb": 0.0,        # 0 = 자동(그 순간 남은 메모리의 절반)
}


def default_path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "Image2PDF" / "settings.json"


class Settings:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_path()
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self._load()

    def _load(self):
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(loaded, dict):
            return
        mode = loaded.get("storage_mode")
        if mode in (STORAGE_ASK, STORAGE_RAM, STORAGE_DISK):
            self._data["storage_mode"] = mode
        limit = loaded.get("ram_limit_gb")
        if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit >= 0:
            self._data["ram_limit_gb"] = float(limit)

    def get(self, key: str) -> Any:
        return self._data.get(key, DEFAULTS[key])

    def set(self, key: str, value: Any):
        self._data[key] = value
        self.save()

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False
