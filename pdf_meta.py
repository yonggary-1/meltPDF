"""
PDF 서지 정보 읽기/쓰기.

- 읽기(read_pdf_meta): "기존 PDF 열기"로 연 PDF의 문서 정보(Info: Title/Author/Subject/Keywords)와 XMP(dc:publisher,
  dc:language, dc:date, dc:identifier)를 읽는다. Info와 XMP가 다르면 Info를 쓴다(많은 프로그램이 Info만 고친다).
- 쓰기(apply_meta): 내보낼 PDF에 Info와 XMP를 함께 쓴다. 두 곳에 모두 써야 여러 PDF 뷰어/관리 프로그램이 같은 값을 본다.
  pikepdf가 XMP에 쓴 값을 Info에도 맞춰 준다(dc:title -> Title, dc:creator -> Author, dc:description -> Subject,
  pdf:Keywords -> Keywords). 언어는 문서 언어(/Lang)에도 넣는다.
  비어 있는 칸은 쓰지 않는다. 출판일/언어가 형식에 맞지 않으면 그 칸만 건너뛴다(서지 정보 창은 저장할 때 미리 막는다).
"""
from __future__ import annotations

from typing import Iterable, List, Optional

import pikepdf

import book_meta
from book_meta import BookMeta


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, frozenset)):
        return "; ".join(str(v) for v in value if str(v).strip())
    return str(value)


def _first(value) -> str:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)[0] if value else ""
    return _text(value)


def read_pdf_meta(path: str, source: str = "") -> BookMeta:
    """PDF의 서지 정보. 읽지 못하면(암호, 손상 등) 빈 BookMeta."""
    m = BookMeta(source=source)
    try:
        with pikepdf.open(path) as pdf:
            info = {}
            try:
                info = {str(k): str(v) for k, v in pdf.docinfo.items()
                        if isinstance(v, pikepdf.String)}
            except Exception:
                pass
            xmp = {}
            try:
                x = pdf.open_metadata()
                for key in ("dc:title", "dc:creator", "dc:description", "dc:subject", "pdf:Keywords",
                            "dc:publisher", "dc:language", "dc:date", "dc:identifier"):
                    try:
                        v = x.get(key)
                    except Exception:
                        v = None
                    if v:
                        xmp[key] = v
            except Exception:
                pass
            m.title = info.get("/Title") or _text(xmp.get("dc:title"))
            m.author = info.get("/Author") or _text(xmp.get("dc:creator"))
            m.subject = info.get("/Subject") or _text(xmp.get("dc:description"))
            m.keywords = info.get("/Keywords") or _text(xmp.get("pdf:Keywords")) or \
                book_meta.join_unique(sorted(str(v) for v in (xmp.get("dc:subject") or ())), ", ")
            m.publisher = _first(xmp.get("dc:publisher"))
            m.language = _first(xmp.get("dc:language"))
            try:
                lang = pdf.Root.get("/Lang")
                if not m.language and isinstance(lang, pikepdf.String):
                    m.language = str(lang)
            except Exception:
                pass
            m.date = _first(xmp.get("dc:date"))
            m.identifier = _text(xmp.get("dc:identifier"))
    except Exception:
        return BookMeta(source=source)
    return m.clean()


def apply_meta(pdf: pikepdf.Pdf, meta: Optional[BookMeta]) -> None:
    """내보낼 PDF(pdf)에 서지 정보를 쓴다. meta가 없거나 비어 있으면 아무것도 하지 않는다."""
    if meta is None:
        return
    meta = meta.clean()
    if meta.is_empty():
        return
    language = meta.language if book_meta.is_valid_language(meta.language) else ""
    date = book_meta.normalize_date(meta.date) if meta.date else None
    with pdf.open_metadata(set_pikepdf_as_editor=False) as x:
        if meta.title:
            x["dc:title"] = meta.title
        authors = book_meta.split_list(meta.author, ";")
        if authors:
            x["dc:creator"] = authors
        if meta.subject:
            x["dc:description"] = meta.subject
        if meta.keywords:
            x["pdf:Keywords"] = meta.keywords
            x["dc:subject"] = book_meta.split_list(meta.keywords, ",;")
        if meta.publisher:
            x["dc:publisher"] = [meta.publisher]
        if language:
            x["dc:language"] = [language]
        if date:
            x["dc:date"] = [date]
        if meta.identifier:
            x["dc:identifier"] = meta.identifier
    if language:
        pdf.Root.Lang = pikepdf.String(language)
