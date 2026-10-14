"""
EPUB 읽기 - epub 안의 이미지를 "책을 읽는 순서"로 꺼낸다(이름 순이 아니다).

epub은 zip 안에 xhtml 쪽들이 들어 있는 책이다. 읽는 순서는 이름이 아니라 content.opf의 spine(쪽 순서)이 정한다:
 META-INF/container.xml -> content.opf -> manifest(파일 목록)와 spine(순서) -> 각 쪽(xhtml)에서 <img>/<svg><image>를
 만나는 순서대로 이미지를 모은다. 만화/사진집 epub은 한 쪽에 이미지 한 장이 보통이라 이 순서가 곧 책 순서다.
- 같은 이미지를 여러 쪽에서 쓰면 처음 나온 자리에만 넣는다. 쪽에서 쓰지 않아도 표지(cover-image)로 지정된 이미지는 맨 앞에 넣는다.
- 이미지는 재인코딩 없이 원본 바이트 그대로 꺼낸다. 이미지가 없는 글 위주 epub은 "이미지가 들어 있지 않습니다"가 된다.
- DRM(저작권 보호)으로 암호화된 이미지/쪽이 있으면 거절한다(우회하지 않는다). 글꼴만 섞어 놓은 난독화는 DRM이 아니므로 무시한다.
- 서지 정보: content.opf의 <metadata>(dc:title, dc:creator, dc:description ...)를 읽어 결과(meta)에 담는다.
"""
from __future__ import annotations

import io
import os
import posixpath
import re
import urllib.parse
import zipfile
from zlib import error as zlib_error
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

import book_meta
import name_codec
import temp_store
from archive_zip import MAX_ENTRY_BYTES, MAX_TOTAL_BYTES, copy_limited
from book_common import (BookError, ExtractedImage, ExtractResult, ProgressFn, is_image_name, local_name, unreadable_entry,
                         noop_progress, parse_xml)

MAX_DOC_BYTES = 50 * 1024 * 1024            # 쪽(xhtml) 하나는 이보다 크면 읽지 않는다
FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}   # 글꼴 난독화(DRM 아님)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


class _ImageRefs(HTMLParser):
    """xhtml에서 이미지 참조를 나타나는 순서대로 모은다: <img src>, <image href/xlink:href>(svg 안)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs: List[str] = []

    def _tag(self, tag, attrs):
        tag = tag.lower().rsplit(":", 1)[-1]
        d = {(k or "").lower(): v for k, v in attrs if v}
        if tag == "img":
            ref = d.get("src")
        elif tag == "image":
            ref = d.get("xlink:href") or d.get("href")
        else:
            return
        if ref:
            self.refs.append(ref)

    def handle_starttag(self, tag, attrs):
        self._tag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._tag(tag, attrs)


def _resolve(base_doc: str, href: str) -> Optional[str]:
    """base_doc(zip 안 경로)에 있는 문서가 가리키는 href를 zip 안 경로로. 바깥 주소/data:/빈 값이면 None."""
    href = (href or "").strip().split("#", 1)[0].split("?", 1)[0]
    if not href or _SCHEME.match(href):
        return None
    href = urllib.parse.unquote(href).replace("\\", "/")
    path = href.lstrip("/") if href.startswith("/") else posixpath.join(posixpath.dirname(base_doc), href)
    path = posixpath.normpath(path)
    if path.startswith("..") or path == ".":
        return None
    return path


class _Zip:
    """epub(zip) 안 파일을 이름으로 찾는 도우미. 이름은 name_codec으로 복원하고, 못 찾으면 대소문자를 무시하고 찾는다."""

    def __init__(self, zf: zipfile.ZipFile):
        self.zf = zf
        infos = zf.infolist()
        self.by_name: Dict[str, zipfile.ZipInfo] = {}
        for info, name in zip(infos, name_codec.decode_zip_names(infos)):
            if not info.is_dir():
                self.by_name.setdefault(name, info)
        self.lower = {n.lower(): n for n in self.by_name}

    def find(self, path: Optional[str]) -> Optional[str]:
        if path is None:
            return None
        if path in self.by_name:
            return path
        return self.lower.get(path.lower())

    def read(self, name: str, limit: int) -> bytes:
        info = self.by_name[name]
        if info.file_size > limit:
            raise BookError(f"epub 안의 '{name}'이 너무 큽니다.")
        try:
            with self.zf.open(info) as f:
                return f.read(limit + 1)[:limit]
        except (zipfile.BadZipFile, zlib_error, EOFError, NotImplementedError) as e:
            raise BookError(f"epub 안의 '{name}'을(를) 읽지 못했습니다: {e}")


def is_epub(zf: zipfile.ZipFile) -> bool:
    """zip이 epub인가: META-INF/container.xml이 있다."""
    try:
        return any(n.lower() == "meta-inf/container.xml" for n in zf.namelist())
    except Exception:
        return False


def _open_zip(path: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise BookError("epub 파일이 손상되었거나 zip 형식이 아닙니다.")
    except OSError as e:
        raise BookError(f"파일을 열 수 없습니다: {e}")


def _package(z: _Zip) -> Tuple[str, object]:
    """content.opf의 경로와 파싱한 루트."""
    opf_path = None
    container = z.find("META-INF/container.xml")
    if container:
        root = parse_xml(z.read(container, 1024 * 1024), "container.xml")
        for rf in root.iter():
            if local_name(rf.tag) == "rootfile" and rf.get("full-path"):
                opf_path = z.find(posixpath.normpath(urllib.parse.unquote(rf.get("full-path"))))
                if opf_path:
                    break
    if opf_path is None:                         # container.xml이 잘못된 책: 첫 .opf를 쓴다
        opf_path = next((n for n in z.by_name if n.lower().endswith(".opf")), None)
    if opf_path is None:
        raise BookError("epub에서 책 정보(content.opf)를 찾지 못했습니다.")
    return opf_path, parse_xml(z.read(opf_path, 16 * 1024 * 1024), "content.opf")


def _reading_order(z: _Zip, opf_path: str, opf) -> Tuple[List[str], List[str], List[str]]:
    """(쪽 문서들의 zip 안 경로를 읽는 순서로, 표지로 지정된 이미지 경로들, spine에 직접 들어 있는 이미지 경로들)."""
    manifest: Dict[str, dict] = {}
    cover_meta = None
    for el in opf.iter():
        name = local_name(el.tag)
        if name == "item" and el.get("id") and el.get("href"):
            manifest[el.get("id")] = {"href": el.get("href"), "type": (el.get("media-type") or "").lower(),
                                      "props": (el.get("properties") or "").split()}
        elif name == "meta" and (el.get("name") or "").lower() == "cover":
            cover_meta = el.get("content")
    docs: List[str] = []
    direct_images: List[str] = []
    for el in opf.iter():
        if local_name(el.tag) == "itemref":
            item = manifest.get(el.get("idref") or "")
            if item is None:
                continue
            path = z.find(_resolve(opf_path, item["href"]))
            if path is None:
                continue
            (direct_images if item["type"].startswith("image/") else docs).append(path)
    covers: List[str] = []
    for item_id, item in manifest.items():
        if "cover-image" in item["props"] or item_id == cover_meta:
            if item["type"].startswith("image/") or is_image_name(item["href"]):
                path = z.find(_resolve(opf_path, item["href"]))
                if path:
                    covers.append(path)
    return docs, covers, direct_images


def _images_in_order(z: _Zip, docs: List[str], covers: List[str], direct: List[str]) -> List[str]:
    order: List[str] = []
    seen = set()

    def add(path: Optional[str]):
        real = z.find(path)
        if real and real not in seen and is_image_name(real):
            seen.add(real)
            order.append(real)

    for c in covers:
        add(c)
    # 쪽(xhtml)을 spine 순서대로 훑으며 이미지 참조를 나온 순서대로 모은다
    for doc in docs:
        scan = _ImageRefs()
        try:
            data = z.read(doc, MAX_DOC_BYTES)
        except BookError:
            continue
        text = data.decode("utf-16", "replace") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("utf-8", "replace")
        try:
            scan.feed(text)
            scan.close()
        except Exception:
            pass
        for ref in scan.refs:
            add(_resolve(doc, ref))
    for d in direct:
        add(d)
    return order


def _read_meta(opf, source: str) -> book_meta.BookMeta:
    """content.opf의 <metadata>에서 서지 정보를 읽는다. 저자는 역할이 없거나 저자(aut)인 creator만 쓴다(없으면 creator 전부)."""
    meta_el = next((el for el in opf.iter() if local_name(el.tag) == "metadata"), None)
    m = book_meta.BookMeta(source=source)
    if meta_el is None:
        return m
    unique_id = opf.get("unique-identifier") or ""
    roles: Dict[str, str] = {}                          # EPUB3: <meta refines="#id" property="role">aut</meta>
    for el in meta_el.iter():
        if local_name(el.tag) == "meta" and (el.get("property") or "") == "role":
            roles[(el.get("refines") or "").lstrip("#")] = "".join(el.itertext()).strip().lower()
    vals: Dict[str, List] = {}
    for el in meta_el.iter():
        name = local_name(el.tag)
        text = "".join(el.itertext()).strip()
        if not text:
            continue
        attrs = {local_name(k): v for k, v in el.attrib.items()}
        vals.setdefault(name, []).append((text, attrs))
    first = lambda key: vals.get(key, [("", {})])[0][0]
    creators = vals.get("creator", [])
    authors = [t for t, a in creators if (a.get("role") or roles.get(a.get("id", ""), "aut")).lower() == "aut"]
    m.title = first("title")
    m.author = book_meta.join_unique(authors or [t for t, _ in creators], "; ")
    m.subject = book_meta.strip_html(first("description"))
    m.keywords = book_meta.join_unique((t for t, _ in vals.get("subject", [])), ", ")
    m.publisher = first("publisher")
    m.language = first("language")
    dates = vals.get("date", [])
    pub = [t for t, a in dates if (a.get("event") or "").lower() == "publication"]
    m.date = pub[0] if pub else (dates[0][0] if dates else "")
    ids = vals.get("identifier", [])
    isbn = [t for t, a in ids if (a.get("scheme") or "").lower() == "isbn" or t.lower().startswith("urn:isbn:")]
    main = [t for t, a in ids if a.get("id") and a.get("id") == unique_id]
    ident = (isbn or main or [t for t, _ in ids] or [""])[0]
    m.identifier = re.sub(r"(?i)^urn:isbn:", "", ident)
    return m.clean()


def _check_drm(z: _Zip, wanted: List[str], docs: List[str]) -> None:
    name = z.find("META-INF/encryption.xml")
    if not name:
        return
    root = parse_xml(z.read(name, 4 * 1024 * 1024), "encryption.xml")
    targets = {n.lower() for n in wanted} | {n.lower() for n in docs}
    for ed in root.iter():
        if local_name(ed.tag) != "EncryptedData":
            continue
        algo, uri = "", ""
        for sub in ed.iter():
            if local_name(sub.tag) == "EncryptionMethod":
                algo = sub.get("Algorithm") or ""
            elif local_name(sub.tag) == "CipherReference":
                uri = sub.get("URI") or ""
        if algo in FONT_OBFUSCATION:
            continue
        target = posixpath.normpath(urllib.parse.unquote(uri)).lower() if uri else ""
        if target in targets:
            raise BookError("저작권 보호(DRM)가 걸린 epub이라 열지 않습니다.")


def estimate_bytes(path: str) -> int:
    """꺼낼 이미지의 대략적인 크기 합계(목차만 읽음). epub 안의 모든 이미지 파일 크기를 더한 값이라 약간 크게 나올 수 있다."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            return sum(i.file_size for i, n in zip(infos, name_codec.decode_zip_names(infos))
                       if not i.is_dir() and is_image_name(n))
    except Exception:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0


def extract_epub(path: str, on_progress: ProgressFn = noop_progress, to_ram: bool = False) -> List[ExtractedImage]:
    zf = _open_zip(path)
    with zf:
        z = _Zip(zf)
        opf_path, opf = _package(z)
        docs, covers, direct = _reading_order(z, opf_path, opf)
        order = _images_in_order(z, docs, covers, direct)
        _check_drm(z, order, docs)
        if sum(z.by_name[n].file_size for n in order) > MAX_TOTAL_BYTES:
            raise BookError("이미지 전체 크기가 너무 큽니다(16GB 초과).")
        results = ExtractResult(meta=_read_meta(opf, os.path.basename(path)))
        total = len(order)
        for done, name in enumerate(order, start=1):
            info = z.by_name[name]
            if info.file_size > MAX_ENTRY_BYTES:
                raise BookError(f"항목 하나가 너무 큽니다(1GB 초과): {name}")
            try:
                try:
                    src = zf.open(info)
                except (zipfile.BadZipFile, zlib_error, EOFError, NotImplementedError):
                    src = None
                if src is None:
                    results.append(unreadable_entry(name, "압축 파일 안의 이 항목을 열지 못했습니다"))       # 못 꺼내도 자리는 지킨다(X 표시)
                else:
                    with src:
                        if to_ram:
                            buf = io.BytesIO()
                            ok = copy_limited(src, buf, name, info.CRC)
                            data = buf.getvalue()
                            keep = bool(data)
                            if keep:
                                results.append(ExtractedImage(label=name, data=data, damaged=not ok))
                        else:
                            out_path = temp_store.new_path(PurePosixPath(name).suffix.lower())
                            with open(out_path, "wb") as dst:
                                ok = copy_limited(src, dst, name, info.CRC)
                            keep = os.path.getsize(out_path) > 0
                            if keep:
                                results.append(ExtractedImage(label=name, path=out_path, damaged=not ok))
                    if not keep:
                        results.append(unreadable_entry(name, "빈 파일(0바이트)입니다" if info.file_size == 0
                                                        else "압축 파일 안에서 내용을 하나도 꺼내지 못했습니다"))
            except OSError as e:
                raise BookError(f"'{name}'을(를) 읽지 못했습니다: {e}")
            on_progress(done, total)
        return results
