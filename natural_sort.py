"""
이름 정렬 - 압축 파일(zip/rar 등)은 안의 파일에 "의미 있는 순서"가 없으므로 이름순으로 정렬한다.

사람이 기대하는 자연 정렬을 한다:
- 숫자 덩어리는 크기로 비교한다 (2 < 10, 그래서 page2.jpg 가 page10.jpg 보다 앞).
- 대소문자는 구분하지 않는다.
- 폴더 경로는 폴더 단위로 나눠 비교한다 (ch2/ 가 ch10/ 보다 앞, 같은 폴더 안 파일끼리 모여 있음).
- 윈도우식 역슬래시 경로도 같은 구분자로 취급한다.
"""
from __future__ import annotations

import re
from typing import Tuple

_DIGITS = re.compile(r"(\d+)")


def _component_key(part: str) -> Tuple:
    # re.split 결과는 항상 [문자, 숫자, 문자, 숫자, ...] 순서라서 같은 자리끼리 같은 종류끼리 비교된다.
    pieces = _DIGITS.split(part.casefold())
    return tuple(int(p) if i % 2 else p for i, p in enumerate(pieces))


def path_key(name: str) -> Tuple:
    """정렬 키. sorted(names, key=path_key) 처럼 쓴다."""
    parts = [p for p in name.replace("\\", "/").split("/") if p]
    return tuple(_component_key(p) for p in parts) + (name,)   # 마지막 name은 완전히 같은 경우의 안정적인 결정용
