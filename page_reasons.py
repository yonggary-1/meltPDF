"""
PDF 쪽을 이미지로 꺼내지 않고 "쪽 그대로" 넣은 이유들 - 이름과 설명, 그리고 이유별 해결 방법 목록(v0.21.0, 사용자 요청).

이유 번호는 pdf_page_image.classify가 정하고(PageItem.pdf_reason, 자세한 내용은 pdf_reason_detail), 썸네일의 [?]를 누르면
page_reason_dialog가 여기 글을 보여 준다.

해결 방법은 논의하면서 이유마다 하나씩 추가한다(사용자 결정). 추가할 때는 SOLUTIONS[이유 번호]에 Solution을 넣으면
창에 버튼이 생긴다(page_fixes.py가 등록). handler(app, item)는 해결한 뒤 목록을 바꾸는 일까지 하고, 끝났으면 True를 돌려준다.
preview(item)가 있으면 창에 결과 모습을 나란히 보여 준다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# 이유 번호 -> (짧은 이름, 설명)
REASONS: Dict[str, Tuple[str, str]] = {
    "locked": ("암호/복사 제한 PDF",
               "이 PDF는 암호가 걸려 있거나 내용 복사를 막아 두었습니다. 그런 PDF에서는 이미지를 꺼내지 않고 "
               "모든 쪽을 쪽 그대로 넣습니다(이미지 내보내기와 같은 원칙)."),
    "annot": ("주석/양식이 있는 쪽",
              "이 쪽에는 주석(메모, 형광펜 등)이나 입력 칸이 있습니다. 이미지로 꺼내면 그것들이 사라지므로 쪽 그대로 넣었습니다."),
    "no_image": ("이미지가 없는 쪽",
                 "이 쪽에는 이미지가 없습니다(글자나 도형만으로 된 쪽)."),
    "unused_images": ("이미지가 여러 장 등록된 쪽",
                      "화면에 그려지는 이미지는 한 장이지만, 쪽 정보에는 이미지가 여러 장 등록되어 있습니다(여러 쪽이 이미지 목록을 "
                      "함께 쓰는 PDF 등). 어떻게 꺼낼지 골라 주세요."),
    "multi_image": ("이미지가 여러 장인 쪽",
                    "이 쪽에는 이미지가 두 장 이상 있습니다(한 장을 조각으로 나눠 놓은 스캔본도 이렇게 보입니다). "
                    "한 장만 꺼내면 나머지가 사라지므로 쪽 그대로 넣었습니다."),
    "inline_image": ("쪽 안에 직접 쓴 이미지",
                     "이미지가 따로 저장되지 않고 쪽 내용 안에 직접 쓰여 있어 원래 바이트로 꺼낼 수 없습니다."),
    "skewed": ("비스듬히 놓인 이미지",
               "이미지가 90도 단위가 아닌 각도로 기울어져 놓여 있습니다. 꺼내면 기울기가 사라지므로 쪽 그대로 넣었습니다."),
    "flipped": ("뒤집혀 놓인 이미지",
                "이미지가 좌우 또는 상하로 뒤집혀 놓여 있습니다. 꺼내면 원래(뒤집기 전) 방향이 되므로 쪽 그대로 넣었습니다."),
    "outside": ("쪽 밖으로 나간 이미지",
                "이미지 일부가 쪽 밖으로 나가 있어 화면에는 잘린 모습으로 보입니다. 꺼내면 잘린 부분까지 나오므로 쪽 그대로 넣었습니다."),
    "stretched": ("비율을 바꿔 놓은 이미지",
                  "이미지의 가로세로 비율과 쪽에 놓인 칸의 비율이 다릅니다(PDF를 만들 때 늘리거나 줄여 놓음). 보통은 원본 비율이 "
                  "원래 모습이지만, 가로·세로 해상도가 다른 스캔(팩스 등)은 PDF에서 보이던 비율이 맞습니다. 모습을 보고 골라 주세요."),
    "clipped": ("일부가 가려진 이미지",
                "이미지 일부가 잘라내기 영역 밖에 있어 화면에는 일부만 보입니다. 꺼내면 가려진 부분까지 나오므로 쪽 그대로 넣었습니다."),
    "drawn_text": ("글자가 있는 쪽",
                   "이미지 말고도 화면에 보이는 글자가 있습니다. 이미지로 꺼내면 글자가 사라지므로 쪽 그대로 넣었습니다."),
    "drawn_other": ("이미지 외에 그려진 것이 있는 쪽",
                    "이미지 말고도 선, 도형, 그러데이션 같은 것이 그려져 있습니다. 이미지로 꺼내면 그것들이 사라지므로 쪽 그대로 넣었습니다."),
    "image_format": ("특수한 이미지 설정",
                     "이미지에 마스크, 색 변환 설정, 특수한 색 공간 같은 것이 붙어 있습니다. 원래 바이트로 꺼내면 "
                     "화면과 다르게 보일 수 있어 쪽 그대로 넣었습니다."),
    "read_fail": ("이미지를 꺼내지 못함",
                  "이 쪽의 이미지 데이터를 꺼내거나 이미지로 읽지 못했습니다."),
    "error": ("판정 중 오류",
              "이 쪽을 살펴보다 예상하지 못한 오류가 나서 쪽 그대로 넣었습니다."),
    "": ("이유 기록 없음",
         "이유가 기록되지 않은 쪽입니다."),
}


@dataclass
class Solution:
    text: str                                   # 버튼 글자
    description: str                            # 버튼 옆(아래)에 보여 줄 설명: 무엇이 바뀌는지
    handler: Callable[[object, object], bool]   # (app, item) -> 처리했으면(창을 닫아도 되면) True
    preview: Optional[Callable[[object], object]] = None   # (item) -> 이 방법의 결과 모습(PIL 그림) - 있으면 나란히 보여 준다


# 이유 번호 -> 해결 방법들(논의하며 하나씩 추가한다)
SOLUTIONS: Dict[str, List[Solution]] = {}
# 모든 원인에 맨 앞에 붙는 "쪽 그대로 두기"(사용자 요청 v0.21.0) - page_fixes.register()가 채운다
KEEP: Optional[Solution] = None


def title(reason: str) -> str:
    return REASONS.get(reason, REASONS[""])[0]


def explain(reason: str) -> str:
    return REASONS.get(reason, REASONS[""])[1]


def solutions(reason: str) -> List[Solution]:
    """창에 보일 해결 방법들: 맨 앞은 항상 "쪽 그대로 두기", 그 뒤에 원인별 방법."""
    return ([KEEP] if KEEP is not None else []) + list(SOLUTIONS.get(reason, ()))
