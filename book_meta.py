"""
서지 정보(메타데이터) 자료형 - 책/문서 파일에서 읽어 온 제목, 저자 등을 담고, PDF로 내보낼 때 넘긴다.

- 문서 형식(epub, fb2, mobi 계열, PDF, 앞으로 추가할 djvu 등)의 읽기 모듈은 이미지와 함께 이 정보를 돌려준다
  (ExtractResult.meta). 압축 파일(zip/rar/cbz/cbr)은 서지 정보가 없으므로 돌려주지 않는다.
- 값은 모두 사람이 읽고 고칠 수 있는 글자다. 저자 여러 명은 "; ", 키워드 여러 개는 ", "로 잇는다.
- 읽은 값을 그대로 쓰지 않고 clean()으로 정리한다: 앞뒤 공백, 줄바꿈(설명 외), 너무 긴 값, HTML 태그(설명).
- PDF에 실제로 쓰는 일은 pdf_meta.py가 한다. 여기는 화면도 PDF도 모른다.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, fields
from typing import Iterable, List, Optional

# (필드 이름, 화면에 보여줄 이름) - 서지 정보 창의 입력 칸 순서이기도 하다
FIELDS = (
    ("title", "제목"),
    ("author", "저자"),
    ("subject", "설명/주제"),
    ("keywords", "키워드"),
    ("publisher", "출판사"),
    ("language", "언어"),
    ("date", "출판일"),
    ("identifier", "식별자(ISBN 등)"),
)
MULTILINE = {"subject"}                    # 줄바꿈을 허용하는 칸
MAX_LEN = {"subject": 8000}                # 그 밖의 칸은 MAX_FIELD
MAX_FIELD = 1000

_TAG = re.compile(r"<[^>]{0,2000}>")
_BLOCK_END = re.compile(r"(?i)</(p|div|li|h[1-6])\s*>|<br\s*/?>")
_DATE = re.compile(r"^\s*(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?![\d-])")
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


@dataclass
class BookMeta:
    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    publisher: str = ""
    language: str = ""
    date: str = ""
    identifier: str = ""
    source: str = ""          # 어디서 읽었는지(파일 이름) - PDF에는 쓰지 않는다

    def values(self) -> dict:
        return {name: getattr(self, name) for name, _ in FIELDS}

    def is_empty(self) -> bool:
        return not any(v.strip() for v in self.values().values())

    def copy(self) -> "BookMeta":
        return BookMeta(**{f.name: getattr(self, f.name) for f in fields(self)})

    def clean(self) -> "BookMeta":
        """값을 정리한 새 BookMeta."""
        out = BookMeta(source=self.source)
        for name, _ in FIELDS:
            value = str(getattr(self, name) or "")
            if name in MULTILINE:
                value = "\n".join(_one_line(line) for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
                value = re.sub(r"\n{3,}", "\n\n", value).strip()
            else:
                value = _one_line(value)
            setattr(out, name, value[:MAX_LEN.get(name, MAX_FIELD)].strip())
        out.date = normalize_date(out.date) or out.date          # "2020-05-17T00:00:00+00:00" -> "2020-05-17"
        if out.language.lower() == "und":                         # "언어 미상" 표시(calibre 등의 기본값)
            out.language = ""
        if out.author.lower() in ("unknown", "unknown author"):   # 저자를 모를 때 변환 도구가 넣는 기본값
            out.author = ""
        return out


def _one_line(s: str) -> str:
    s = "".join(ch if ch.isprintable() or ch == " " else " " for ch in s)
    return re.sub(r"\s+", " ", s).strip()


def strip_html(s: str) -> str:
    """설명 칸에 HTML이 들어 있는 책(epub, mobi에 흔함): 문단 끝은 줄바꿈으로, 태그는 지우고, &amp; 같은 것은 푼다."""
    if not s or "<" not in s and "&" not in s:
        return s or ""
    s = _BLOCK_END.sub("\n", s)
    s = _TAG.sub("", s)
    return html.unescape(s)


def join_unique(values: Iterable[str], sep: str) -> str:
    """빈 값과 중복(대소문자 무시)을 빼고 sep로 잇는다."""
    out: List[str] = []
    seen = set()
    for v in values:
        v = _one_line(v or "")
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return sep.join(out)


def split_list(s: str, seps: str = ";") -> List[str]:
    """"A; B" -> ["A", "B"] (seps의 글자 중 하나로 나눈다)."""
    parts = re.split("[" + re.escape(seps) + "]", s or "")
    return [p.strip() for p in parts if p.strip()]


def normalize_date(s: str) -> Optional[str]:
    """출판일을 PDF(XMP)에 넣을 수 있는 꼴로: "2020", "2020-05", "2020-05-17"(뒤에 시간이 붙어 있으면 뗀다).
    해석할 수 없으면 None."""
    m = _DATE.match(s or "")
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    if mo and not 1 <= int(mo) <= 12 or d and not 1 <= int(d) <= 31:
        return None
    return "-".join(p for p in (y, mo, d) if p)


def is_valid_language(s: str) -> bool:
    """"ko", "en-US", "zh-Hant" 같은 언어 코드인가."""
    return bool(_LANG.match((s or "").strip()))


def problems(meta: BookMeta) -> List[str]:
    """저장하기 전에 알려야 할 형식 문제(빈 칸은 문제 아님)."""
    out = []
    if meta.date.strip() and normalize_date(meta.date) is None:
        out.append("출판일은 2020, 2020-05, 2020-05-17 같은 꼴로 입력하세요.")
    if meta.language.strip() and not is_valid_language(meta.language):
        out.append("언어는 ko, en, en-US 같은 언어 코드로 입력하세요.")
    return out
