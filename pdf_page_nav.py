"""
[페이지 추출 N장] 버튼(하단, [깨진 이미지 N장] 옆) - PDF에서 이미지로 꺼내지 못하고 쪽 그대로 넣은(파란 테두리) 항목을
찾아가는 버튼(v0.21.0, 사용자 요청). 동작은 [깨진 이미지 N장]과 같다(item_nav.ItemNav): 누를 때마다 맨 앞부터 차례로 선택하고
화면 가운데로, 상태 줄에 "페이지 추출 2/5: 이름 (원인)". 바탕은 옅은 파랑. 원인과 해결 방법은 타일의 [?]로 본다.
"""
from __future__ import annotations

import page_reasons
from item_nav import ItemNav


class PdfPageNav(ItemNav):
    NAME = "페이지 추출"
    BG = "#d6e4f8"            # 옅은 파랑
    BG_ACTIVE = "#b9d0f2"
    FG = "#163f7a"

    def matches(self, item) -> bool:
        return item.kind == "pdf_page"

    def describe(self, item) -> str:
        return page_reasons.title(getattr(item, "pdf_reason", ""))
