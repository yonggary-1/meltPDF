"""
[깨진 이미지 N장] 버튼(하단, [전체 삭제] 옆) - 목록에서 빨간 테두리(깨졌거나 못 읽은) 이미지를 찾아가는 버튼(v0.19.6, 사용자 요청).

N은 완전하지 않은(item.damaged - 일부만 읽힘, 머리 복구, 못 읽음 모두) 이미지 수. 동작은 item_nav.ItemNav(공통)와 같다:
누를 때마다 맨 앞부터 차례로 선택하고 화면 가운데로, 상태 줄에 "깨진 이미지 2/5: 이름 (종류)". 바탕은 옅은 빨강.
"""
from __future__ import annotations

from item_nav import ItemNav


class DamagedNav(ItemNav):
    NAME = "깨진 이미지"
    BG = "#f6d4d1"            # 옅은 빨강
    BG_ACTIVE = "#efb5b0"
    FG = "#8a1c14"

    def matches(self, item) -> bool:
        return bool(item.damaged)

    def describe(self, item) -> str:
        return "읽지 못함" if item.unreadable else ("머리 부분 복구" if getattr(item, "repaired", False) else "일부만 표시")
