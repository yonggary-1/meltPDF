"""
이름 처리 공용 기능 - 파일/폴더 이름에 관한 일을 한 곳에 모은다.

1. 압축 파일(zip) 안의 깨진 이름 복원: decode_zip_names
   zip은 이름의 글자 인코딩을 적어 두지 않는 경우가 많다(윈도우 한글/일본어/중국어판이 만든 zip은 그 나라 인코딩 그대로).
   그래서 파일 하나씩이 아니라 "압축 파일 전체의 이름들"을 보고 가장 그럴듯한 인코딩 하나를 고른다.
2. 윈도우에서 쓸 수 있는 이름으로 정리: clean_component / safe_name (금지 글자, 끝의 점/공백, 예약 이름, 길이)
3. 같은 이름이 겹칠 때 " (1)", " (2)"를 붙여 겹치지 않게 만들기: unique_name

주의(한계): 한자만으로 된 짧은 이름은 일본어/중국어/한국어(한자)를 구별할 방법이 바이트에 없다. 그럴 때는 한국어
(cp949)를 우선한다. 가나(일본어)나 한글이 하나라도 섞여 있으면 거의 확실히 구별된다.
"""
from __future__ import annotations

import os
import re
import unicodedata
import zipfile
from typing import Dict, Iterable, List, Optional, Set

# ---------------------------------------------------------------- 1. zip 이름 복원

# 후보 순서가 곧 동점일 때의 우선순위다(한국어 사용자 기준).
_CANDIDATES = ("cp949", "cp932", "gbk", "big5")


def _euckr_ok(ch: str) -> bool:
    """KS X 1001 완성형 한글 2350자(실제 한글 문서에서 거의 전부 쓰는 글자)에 드는가.
    cp949의 확장 영역(나머지 8822자)은 일본어/중국어 바이트를 잘못 읽을 때 주로 나온다."""
    try:
        b = ch.encode("cp949")
    except UnicodeEncodeError:
        return False
    return len(b) == 2 and 0xB0 <= b[0] <= 0xC8 and b[1] >= 0xA1


def _char_score(ch: str, kana_ok: bool = True) -> int:
    """글자 하나가 "실제 파일 이름에 쓰일 법한가"의 점수. 엉뚱한 인코딩으로 읽으면 이상한 글자가 많이 나온다."""
    o = ord(ch)
    if o < 0x80:
        return 0 if ch.isprintable() else -5
    if 0xAC00 <= o <= 0xD7A3:                       # 한글 음절
        return 2 if _euckr_ok(ch) else -2           # 완성형 2350자 밖의 글자는 일본어 등을 잘못 읽을 때 나온다
    if 0x3040 <= o <= 0x30FF:                       # 히라가나/가타카나 - 일본어(cp932)로 읽었을 때만 점수를 준다
        return 2 if kana_ok else -2                 # (gbk/big5/cp949에도 가나가 있어서 엉뚱한 글자가 가나로 나올 수 있다)
    if 0xFF61 <= o <= 0xFF9F:                       # 반각 가타카나 - 다른 인코딩으로 잘못 읽을 때만 나온다
        return -3
    if 0x4E00 <= o <= 0x9FFF:                       # 한자
        return 1
    if 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFF60:   # 전각 문장부호/기호
        return 1
    if 0xE000 <= o <= 0xF8FF or o == 0xFFFD:        # 사용자 정의/대체 문자
        return -6
    if 0x3130 <= o <= 0x318F or 0x1100 <= o <= 0x11FF:    # 한글 자모
        return -1
    return -1                                       # 키릴/그리스/기호 등 - 쓰일 수는 있으나 드물다


def _is_hangul(ch: str) -> bool:
    return 0xAC00 <= ord(ch) <= 0xD7A3


def _is_ideo(ch: str) -> bool:
    return 0x4E00 <= ord(ch) <= 0x9FFF


def _name_score(name: str, kana_ok: bool = True) -> int:
    score = sum(_char_score(c, kana_ok) for c in name)
    has_hangul = any(0xAC00 <= ord(c) <= 0xD7A3 for c in name)
    has_kana = any(0x3040 <= ord(c) <= 0x30FF for c in name)
    if has_hangul and has_kana:                     # 한글과 가나가 한 이름에 같이 있는 일은 거의 없다
        score -= 6
    # 한글과 한자가 글자 단위로 번갈아 나오는 이름은 중국어(GBK)를 한국어로 잘못 읽은 모양이다.
    # (실제 한국어 이름은 "삼국지 三國志"처럼 덩어리로 나뉜다.)
    for a, b in zip(name, name[1:]):
        if _is_hangul(a) != _is_hangul(b) and (_is_ideo(a) or _is_ideo(b)) and (_is_hangul(a) or _is_hangul(b)):
            score -= 4
    return score


def guess_encoding(raws: Iterable[bytes]) -> str:
    """이름 바이트들을 보고 인코딩을 고른다. UTF-8로 깔끔히 읽히면 UTF-8, 아니면 점수가 가장 높은 후보."""
    raws = [r for r in raws if any(b >= 0x80 for b in r)]
    if not raws:
        return "utf-8"
    try:
        for r in raws:
            r.decode("utf-8")
        return "utf-8"                              # 한글/일본어 바이트열이 우연히 UTF-8 규칙을 지킬 확률은 매우 낮다
    except UnicodeDecodeError:
        pass
    best, best_score = None, None
    for enc in _CANDIDATES:
        total = 0
        try:
            for r in raws:
                total += _name_score(r.decode(enc), kana_ok=(enc == "cp932"))
        except UnicodeDecodeError:
            continue                                # 한 이름이라도 못 읽으면 이 인코딩이 아니다
        if best_score is None or total > best_score:     # 동점이면 앞선 후보 유지
            best, best_score = enc, total
    return best or "cp437"


def decode_zip_names(infos: List[zipfile.ZipInfo]) -> List[str]:
    """zip 항목들의 이름을 복원해 같은 순서로 돌려준다(구분자는 /로 통일).
    UTF-8 표시(0x800)가 있는 항목은 파이썬이 이미 맞게 읽었으므로 그대로 두고, 없는 항목들은 전체를 보고 인코딩을 고른다."""
    raws: Dict[int, bytes] = {}
    for idx, info in enumerate(infos):
        if not (info.flag_bits & 0x800):
            try:
                raws[idx] = info.filename.encode("cp437")   # 파이썬이 cp437로 읽은 것을 원래 바이트로 되돌린다
            except UnicodeEncodeError:
                pass                                          # 이미 다른 방식으로 읽힌 이름 - 건드리지 않는다
    enc = guess_encoding(raws.values()) if raws else "utf-8"
    names: List[str] = []
    for idx, info in enumerate(infos):
        name = info.filename
        raw = raws.get(idx)
        if raw is not None and any(b >= 0x80 for b in raw):
            try:
                name = raw.decode(enc)
            except UnicodeDecodeError:
                name = raw.decode(enc, errors="replace")      # 한 이름만 이상한 경우 그 이름만 일부 대체 문자
        names.append(name.replace("\\", "/"))
    return names


# ---------------------------------------------------------------- 2. 윈도우용 이름 정리

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_STEM_CHARS = 150        # 윈도우 한 이름 한도(255)와 경로 길이에 여유를 둔다


def clean_component(name: str) -> str:
    """이름 한 조각에서 쓸 수 없는 글자를 _로 바꾸고 끝의 공백/마침표를 없앤다(윈도우는 끝의 점/공백을 허용하지 않는다)."""
    return _INVALID_CHARS.sub("_", unicodedata.normalize("NFC", name)).strip().rstrip(". ")


def safe_name(name: str, fallback: str = "_") -> str:
    """경로가 아닌 "이름 하나"를 윈도우에서 만들 수 있는 모양으로 바꾼다. 일본어/중국어 등은 그대로 둔다.
    확장자는 보존하고, 너무 길면 확장자 앞부분을 줄인다."""
    name = clean_component(name)
    stem, ext = os.path.splitext(name)
    if len(ext) > 16 or not ext[1:].isalnum():            # 확장자처럼 안 생긴 것은 이름의 일부로 본다
        stem, ext = name, ""
    stem = stem.rstrip(". ")
    if len(stem) > MAX_STEM_CHARS:
        stem = stem[:MAX_STEM_CHARS].rstrip(". ")
    if not stem:
        stem = fallback
    if stem.split(".")[0].upper() in _RESERVED:
        stem = "_" + stem
    return stem + ext


# ---------------------------------------------------------------- 3. 겹치는 이름 처리

def unique_name(name: str, taken: Set[str]) -> str:
    """name이 taken(소문자 이름들의 집합)과 겹치면 확장자 앞에 " (1)", " (2)"...를 붙여 안 겹치는 이름으로 돌려주고,
    그 이름을 taken에 넣는다. 윈도우는 대소문자를 구별하지 않으므로 소문자로 비교한다."""
    stem, ext = os.path.splitext(name)
    candidate, n = name, 0
    while candidate.lower() in taken:
        n += 1
        candidate = f"{stem} ({n}){ext}"
    taken.add(candidate.lower())
    return candidate


def unique_dir(parent: str, name: str) -> str:
    """parent 안에 아직 없는 폴더 경로를 돌려준다(이미 있으면 " (1)", " (2)"...). 폴더를 만들지는 않는다."""
    candidate, n = name, 0
    while os.path.exists(os.path.join(parent, candidate)):
        n += 1
        candidate = f"{name} ({n})"
    return os.path.join(parent, candidate)
