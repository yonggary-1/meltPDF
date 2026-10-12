"""
DjVu 읽기 - djvu의 각 쪽을 원래 해상도 그대로 풀어 PNG로 꺼낸다(쪽 순서대로).

djvu의 쪽은 JPEG/PNG 같은 이미지 파일로 들어 있지 않고, 흑백 글자층(JB2), 배경층(IW44), 전경 색으로 나뉘어 djvu 전용 압축으로
들어 있다. 그대로 꺼내도 열 수 있는 프로그램이 없으므로, DjVuLibre의 ddjvu로 쪽을 크기 변경 없이(원래 해상도) 풀어서
PNG(무손실)로 저장한다. "원본 바이트"는 아니지만 "원본 픽셀"은 그대로다.
- 흑백 쪽은 1비트 PNG(PBM -> PNG), 회색 쪽은 회색 PNG, 컬러 쪽은 RGB PNG. 쪽의 원래 dpi를 PNG에 적어 두어, 스캔 이미지와
  같은 규칙으로 PDF 쪽 크기가 원래 종이 크기가 된다.
- ddjvu 한 번 실행으로 여러 쪽을 PNM 그림으로 차례로 받아 한 쪽씩 PNG로 바꾼다(한 쪽 분량만 메모리에 둔다).
  풀다가 멈추면 멈춘 쪽만 따로 다시 풀어 보고(안 되면 건너뜀), 다음 쪽부터 다시 받는다.
- 서지 정보: djvused의 print-meta(문서에 들어 있는 title, author, subject, keywords, publisher, year 등).
- 꺼낼 크기 추정(메모리/디스크 결정용): 파일의 쪽 정보(INFO: 가로, 세로)와 층 종류(흑백/컬러)를 직접 읽어 계산한다.
"""
from __future__ import annotations

import io
import os
import re
import struct
import tempfile
from typing import Dict, List, Optional, Tuple

from PIL import Image

import book_meta
import djvu_tool
import temp_store
from archive_zip import MAX_TOTAL_BYTES
from book_common import BookError, ExtractedImage, ExtractResult, ProgressFn, noop_progress

_COLOR_CHUNKS = {b"BG44", b"BGjp", b"BG2k", b"FG44", b"FGjp", b"FG2k", b"FGbz"}
_PNM_MAGIC = {b"P4": 1, b"P5": 1, b"P6": 3}
PNG_LEVEL = 4                              # 압축 정도(무손실, 0~9) - 큰 컬러 쪽을 너무 오래 붙잡지 않게 중간값
MAX_PAGE_PIXELS = 400_000_000


def looks_like_djvu(head: bytes) -> bool:
    if head[:4] == b"AT&T":
        head = head[4:]
    return head[:4] == b"FORM" and head[8:12] in (b"DJVU", b"DJVM")


# ------------------------------------------------------------------ 크기 추정 (IFF 구조를 직접 읽음)
def _chunks(f, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        cid, size = head[:4], struct.unpack(">I", head[4:8])[0]
        yield cid, pos + 8, size
        pos += 8 + size + (size & 1)


def page_infos(path: str) -> List[Tuple[int, int, bool, int]]:
    """(가로, 세로, 컬러인가, dpi) 쪽 목록(파일에 든 순서 = 쪽 순서). 한 파일에 쪽이 다 들어 있는(bundled) 경우만 - 아니면 빈 목록."""
    out = []
    with open(path, "rb") as f:
        size = os.path.getsize(path)
        start = 4 if f.read(4) == b"AT&T" else 0
        f.seek(start)
        if f.read(4) != b"FORM":
            return out
        form_size = struct.unpack(">I", f.read(4))[0]
        kind = f.read(4)
        end = min(size, start + 8 + form_size)

        def page(form_start: int, form_end: int):
            w = h = dpi = 0
            color = False
            for cid, data, n in _chunks(f, form_start, form_end):
                if cid == b"INFO" and n >= 4:
                    f.seek(data)
                    info = f.read(min(n, 10))
                    w, h = struct.unpack(">HH", info[:4])
                    if len(info) >= 8:
                        dpi = struct.unpack("<H", info[6:8])[0]      # dpi만 little-endian(규격)
                elif cid in _COLOR_CHUNKS:
                    color = True
            if w and h:
                out.append((w, h, color, dpi if 25 <= dpi <= 6000 else 0))

        if kind == b"DJVU":
            page(start + 12, end)
        elif kind == b"DJVM":
            for cid, data, n in _chunks(f, start + 12, end):
                if cid == b"FORM":
                    f.seek(data)
                    if f.read(4) == b"DJVU":
                        page(data + 4, data + n)
    return out


def estimate_bytes(path: str) -> int:
    """PNG로 풀었을 때의 대략적인 크기: 흑백 쪽은 1비트 원본의 1/3, 컬러 쪽은 RGB 원본의 1/2로 본다."""
    try:
        infos = page_infos(path)
    except (OSError, struct.error):
        infos = []
    if infos:
        return sum((w * h * 3 // 2) if color else (w * h // 24) for w, h, color, _dpi in infos)
    try:
        return os.path.getsize(path) * 20
    except OSError:
        return 0


# ------------------------------------------------------------------ 서지 정보
_META_LINE = re.compile(r'^\s*([A-Za-z][\w-]*)\s+"((?:[^"\\]|\\.)*)"\s*$')


def _unescape(s: str) -> str:
    """djvused 문자열의 역슬래시 표기를 푼다. 8진수(\\352 등)는 UTF-8 바이트이므로 바이트로 모아 한 번에 읽는다."""
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            m = re.match(r"[0-7]{1,3}", s[i + 1:])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
            t = s[i + 1]
            out += {"n": "\n", "t": "\t", "r": "\r"}.get(t, t).encode("utf-8")
            i += 2
            continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def parse_meta(text: str, source: str) -> book_meta.BookMeta:
    values: Dict[str, str] = {}
    for line in text.split("\n"):
        m = _META_LINE.match(line)
        if m:
            values.setdefault(m.group(1).lower(), _unescape(m.group(2)))
    meta = book_meta.BookMeta(source=source)
    meta.title = values.get("title", "")
    meta.author = values.get("author", "")
    meta.subject = values.get("subject") or values.get("description") or values.get("note", "")
    meta.keywords = values.get("keywords", "")
    meta.publisher = values.get("publisher", "")
    meta.language = values.get("language") or values.get("lang", "")
    meta.date = values.get("date") or values.get("year", "")
    meta.identifier = values.get("isbn", "")
    return meta.clean()


# ------------------------------------------------------------------ 쪽 풀기
def _read_exact(stream, n: int) -> bytes:
    parts = []
    while n > 0:
        chunk = stream.read(min(n, 1 << 20))
        if not chunk:
            break
        parts.append(chunk)
        n -= len(chunk)
    return b"".join(parts)


def _read_pnm(stream) -> Optional[bytes]:
    """PNM 그림 하나(머리 + 픽셀)를 바이트로 읽는다. 스트림이 끝났으면 None, 중간에서 끊겼으면 BookError."""
    magic = stream.read(2)
    if not magic:
        return None
    if magic not in _PNM_MAGIC:
        raise BookError("ddjvu 출력이 예상한 형식이 아닙니다.")
    header = bytearray(magic)
    fields: List[int] = []
    need = 2 if magic == b"P4" else 3
    token = b""
    while len(fields) < need:
        c = stream.read(1)
        if not c:
            raise BookError("ddjvu 출력이 중간에서 끊겼습니다.")
        header += c
        if c == b"#":                                    # 주석: 줄 끝까지 건너뜀
            while c not in (b"\n", b""):
                c = stream.read(1)
                header += c
            continue
        if c.isspace():
            if token:
                fields.append(int(token))
                token = b""
        elif c.isdigit():
            token += c
        else:
            raise BookError("ddjvu 출력이 예상한 형식이 아닙니다.")
    w, h = fields[0], fields[1]
    if not (0 < w and 0 < h and w * h <= MAX_PAGE_PIXELS):
        raise BookError("쪽 크기가 너무 크거나 잘못되었습니다.")
    if magic == b"P4":
        size = ((w + 7) // 8) * h
    else:
        if fields[2] > 255:
            raise BookError("16비트 PNM은 지원하지 않습니다.")
        size = w * h * _PNM_MAGIC[magic]
    data = _read_exact(stream, size)
    if len(data) < size:
        raise BookError("ddjvu 출력이 중간에서 끊겼습니다.")
    return bytes(header) + data


def _to_png(pnm: bytes, info: Optional[Tuple[int, int, bool, int]]) -> bytes:
    """PNM -> PNG. 쪽의 원래 dpi를 알면(쪽 정보의 크기가 맞을 때만) PNG에 적어 둔다 - 스캔 이미지처럼 PDF 쪽이 원래 종이 크기가 된다."""
    with Image.open(io.BytesIO(pnm)) as im:
        im.load()
        out = io.BytesIO()
        extra = {}
        if info and info[3] and im.size == (info[0], info[1]):
            extra["dpi"] = (info[3], info[3])
        im.save(out, "PNG", compress_level=PNG_LEVEL, **extra)
    return out.getvalue()


def _stream(ddjvu: str, path: str, first: int, last: int, on_page, infos) -> Tuple[int, str]:
    """first~last쪽을 받아 on_page(쪽 번호, png)를 부른다. (받은 쪽 수, 오류 문구)."""
    got = 0
    with tempfile.TemporaryFile() as err:
        proc = djvu_tool.open_pages(ddjvu, path, first, last, err)
        try:
            while first + got <= last:
                try:
                    pnm = _read_pnm(proc.stdout)
                except BookError:
                    break
                if pnm is None:
                    break
                n = first + got
                on_page(n, _to_png(pnm, infos[n - 1] if n <= len(infos) else None))
                got += 1
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=60)
            except Exception:
                proc.kill()
        err.seek(0)
        msg = err.read().decode("utf-8", "replace").strip()
    return got, msg.splitlines()[-1] if msg else ""


def extract_djvu(path: str, on_progress: ProgressFn = noop_progress, to_ram: bool = False) -> List[ExtractedImage]:
    ddjvu, djvused = djvu_tool.find_tools()
    src, copy = djvu_tool.input_path(path)
    try:
        out = djvu_tool.run_djvused(djvused, src, "n; print-meta")
        lines = out.split("\n", 1)
        try:
            pages = int(lines[0].strip())
        except ValueError:
            raise BookError("djvu의 쪽 수를 읽지 못했습니다. 손상된 파일일 수 있습니다.")
        results = ExtractResult(meta=parse_meta(lines[1] if len(lines) > 1 else "", os.path.basename(path)))
        if estimate_bytes(path) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        try:
            infos = page_infos(path)
        except (OSError, struct.error):
            infos = []
        if len(infos) != pages:
            infos = []                               # 쪽 정보가 쪽 수와 안 맞으면(쪽이 다른 파일에 있는 djvu 등) dpi를 쓰지 않는다
        width = max(4, len(str(pages)))
        images: List[ExtractedImage] = []

        def on_page(n: int, png: bytes):
            label = f"page_{n:0{width}d}.png"
            if to_ram:
                images.append(ExtractedImage(label=label, data=png))
            else:
                p = temp_store.new_path(".png")
                try:
                    with open(p, "wb") as f:
                        f.write(png)
                except OSError as e:
                    raise BookError(f"'{label}'을(를) 저장하지 못했습니다: {e}")
                images.append(ExtractedImage(label=label, path=p))
            on_progress(n, pages)

        first = 1
        while first <= pages:
            got, msg = _stream(ddjvu, src, first, pages, on_page, infos)
            if first + got > pages:
                break
            stop = first + got           # 여기서 멈췄다. 이 쪽 출력이 덜 끝난 채 뒤쪽 오류로 끊겼을 수도 있으니 이 쪽만 따로 다시 풀어 본다
            got1, msg1 = _stream(ddjvu, src, stop, stop, on_page, infos)
            if not got1:
                why = msg1 or msg
                results.warnings.append(f"{stop}쪽: 풀지 못했습니다{f' ({why})' if why else ''}. 목록에서 뺐습니다.")
            first = stop + 1
        results.extend(images)
        return results
    finally:
        if copy:
            try:
                os.remove(copy)
            except OSError:
                pass
