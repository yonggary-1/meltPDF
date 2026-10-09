"""
FB2 읽기 - FictionBook(.fb2, 압축한 .fb2.zip)에 들어 있는 이미지를 책에 나오는 순서로 꺼낸다.

fb2는 XML 한 파일이다. 이미지는 문서 맨 끝의 <binary id="..." content-type="image/...">에 base64로 들어 있고,
본문에서 <image l:href="#id"/>로 불러 쓴다. 표지(<coverpage>)는 본문보다 앞의 description 안에 있다.
그래서 문서에 <image>가 나오는 순서(표지 -> 본문)대로 이미지를 모은다. 같은 이미지를 여러 번 쓰면 처음 자리에만 넣는다.
본문에서 부르지 않은 이미지(binary)는, 부른 이미지가 하나도 없을 때만 binary 순서로 넣는다.
- 이미지는 재인코딩 없이 base64만 풀어서 그대로 꺼낸다. 이름은 binary의 id(+내용에 맞춘 확장자).
- fb2.zip은 안에 .fb2 파일 하나가 들어 있는 zip이다.
- 큰 파일을 위해 XML을 한꺼번에 올리지 않고 조금씩 읽는다(iterparse). ENTITY 선언이 있는 파일은 거절한다.
"""
from __future__ import annotations

import base64
import binascii
import os
import zipfile
import xml.etree.ElementTree as ET
from typing import BinaryIO, Dict, List, Optional

import temp_store
from book_common import (BookError, ExtractedImage, ExtractResult, ProgressFn, local_name, noop_progress)
from archive_zip import MAX_ENTRY_BYTES, MAX_TOTAL_BYTES

_EXT_BY_TYPE = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "image/bmp": ".bmp", "image/webp": ".webp", "image/tiff": ".tif"}


def _ext_for(data_head: bytes, content_type: str) -> str:
    import image_export
    fmt = image_export.sniff_format(data_head)
    if fmt:
        return "." + fmt
    return _EXT_BY_TYPE.get((content_type or "").lower().strip(), "")


def looks_like_fb2(head: bytes) -> bool:
    """파일 앞부분이 fb2(FictionBook XML)로 보이는가."""
    return b"<FictionBook" in head or b"<fictionbook" in head


def zip_fb2_name(zf: zipfile.ZipFile) -> Optional[str]:
    """zip 안에 .fb2 파일이 정확히 하나 있으면 그 이름(없거나 여럿이면 None)."""
    names = [i.filename for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(".fb2")]
    return names[0] if len(names) == 1 else None


def estimate_bytes(path: str) -> int:
    """이미지 크기 추정: base64는 원본의 약 4/3이므로 파일 크기의 3/4. fb2.zip은 압축을 푼 크기로 본다."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                name = zip_fb2_name(zf)
                if name:
                    return zf.getinfo(name).file_size * 3 // 4
        return os.path.getsize(path) * 3 // 4
    except Exception:
        return 0


class _Chain:
    """이미 읽어 본 앞부분(head)을 다시 앞에 붙여 주는 읽기 전용 스트림 - XML 파서가 처음부터 읽을 수 있게 한다."""

    def __init__(self, head: bytes, stream: BinaryIO):
        self._head = head
        self._s = stream

    def read(self, n: int = -1) -> bytes:
        if self._head:
            if n is None or n < 0:
                out, self._head = self._head, b""
                return out + self._s.read()
            out, self._head = self._head[:n], self._head[n:]
            if len(out) < n:
                out += self._s.read(n - len(out))
            return out
        return self._s.read(n)


def _parse(stream: BinaryIO, to_ram: bool, on_progress: ProgressFn, results: ExtractResult) -> List[ExtractedImage]:
    head = stream.read(65536)
    stream = _Chain(head, stream)
    if b"<!ENTITY" in head:
        raise BookError("fb2에 허용하지 않는 엔티티 선언이 있어 열지 않습니다.")
    if not looks_like_fb2(head):
        raise BookError("fb2(FictionBook) 파일이 아닙니다.")

    order: List[str] = []                       # 문서에 <image>가 나온 순서의 id
    seen = set()
    blobs: Dict[str, ExtractedImage] = {}       # binary id -> 꺼낸 이미지
    binary_order: List[str] = []
    total_bytes = 0
    in_binary_depth = 0
    try:
        for event, el in ET.iterparse(stream, events=("start", "end")):
            name = local_name(el.tag)
            if event == "start":
                if name == "binary":
                    in_binary_depth += 1
                continue
            if name == "image" and not in_binary_depth:
                href = ""
                for k, v in el.attrib.items():
                    if local_name(k) == "href":
                        href = v
                if href.startswith("#"):
                    bid = href[1:].strip()
                    if bid and bid not in seen:
                        seen.add(bid)
                        order.append(bid)
            elif name == "binary":
                in_binary_depth -= 1
                bid = (el.get("id") or "").strip()
                text = el.text or ""
                ctype = el.get("content-type") or ""
                el.clear()
                if not bid or not text.strip():
                    continue
                try:
                    data = base64.b64decode("".join(text.split()), validate=False)
                except (binascii.Error, ValueError):
                    results.warnings.append(f"{bid}: 이미지 데이터를 풀지 못했습니다. 목록에서 뺐습니다.")
                    continue
                del text
                ext = _ext_for(data[:16], ctype)
                if not ext:
                    continue                        # 이미지가 아니거나 pdf로 만들 수 없는 형식(svg 등)의 binary
                if len(data) > MAX_ENTRY_BYTES:
                    raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {bid}")
                total_bytes += len(data)
                if total_bytes > MAX_TOTAL_BYTES:
                    raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
                stem, bext = os.path.splitext(bid)
                if bext.lower() in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"):
                    label = bid if (bext.lower() == ext or {bext.lower(), ext} == {".jpg", ".jpeg"}) else stem + ext   # 이름의 확장자가 내용과 다르면 내용에 맞춘다
                else:
                    label = bid + ext
                if to_ram:
                    blobs[bid] = ExtractedImage(label=label, data=data)
                else:
                    out_path = temp_store.new_path(ext)
                    with open(out_path, "wb") as f:
                        f.write(data)
                    blobs[bid] = ExtractedImage(label=label, path=out_path)
                binary_order.append(bid)
                on_progress(len(binary_order), 0)
            elif name in ("p", "section", "title", "emphasis", "strong", "a") and not in_binary_depth:
                el.clear()                          # 본문 글은 쓰지 않으니 메모리에서 바로 버린다(image 자리는 위에서 이미 기록함)
    except ET.ParseError as e:
        raise BookError(f"fb2를 읽지 못했습니다(XML 오류): {e}")
    except UnicodeError as e:
        raise BookError(f"fb2의 글자 코드를 읽지 못했습니다: {e}")

    final = [b for b in order if b in blobs]
    if not final:
        final = list(binary_order)                  # 본문에서 부른 이미지가 없으면 binary 순서
    else:
        missing = [b for b in order if b not in blobs]
        if missing:
            results.warnings.append("본문에서 쓰는데 파일에 없는 이미지 " + str(len(missing)) + "개: " + ", ".join(missing[:10]))
    return [blobs[b] for b in final]


def extract_fb2(path: str, on_progress: ProgressFn = noop_progress, to_ram: bool = False) -> List[ExtractedImage]:
    results = ExtractResult()
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                name = zip_fb2_name(zf)
                if name is None:
                    raise BookError("zip 안에서 fb2 파일 하나를 찾지 못했습니다.")
                with zf.open(name) as stream:
                    images = _parse(stream, to_ram, on_progress, results)
        else:
            with open(path, "rb") as stream:
                images = _parse(stream, to_ram, on_progress, results)
    except (zipfile.BadZipFile, OSError) as e:
        raise BookError(f"fb2를 열지 못했습니다: {e}")
    results.extend(images)
    on_progress(len(images), len(images))
    return results
