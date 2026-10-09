"""
목차(중앙 디렉터리)가 잘리거나 깨진 zip을 "앞에서부터 훑어서" 복구해 읽는다.

zip은 파일 끝에 전체 목차가 있어서, 다운로드가 끊기거나 끝이 잘리면 파이썬 zipfile은 아예 열지 못한다. 하지만 각 파일은 자기 앞에
"로컬 헤더"(이름, 압축 방식, 크기)를 달고 차례로 저장되어 있으므로, 처음부터 헤더를 따라가면 끝이 잘리기 전까지의 파일들은 꺼낼 수 있다.
- 크기가 헤더에 있으면 그만큼 건너뛰고, 크기를 나중에 적는 방식(데이터 설명자)이면 deflate 데이터를 읽어 끝을 찾는다.
- 마지막 파일이 중간에서 끊겼으면 읽을 수 있는 데까지 돌려주고 "손상됨"으로 알린다(archive_zip의 기존 손상 처리가 그대로 받는다).
- 지원: 저장(stored), deflate. 그 밖의 압축 방식(bzip2/lzma 등)과 암호 걸린 항목은 열지 못하고 호출하는 쪽이 사유를 알린다.
이 모듈은 zipfile.ZipFile처럼 infolist()/open(info)를 제공하는 읽기 전용 객체를 돌려줄 뿐, 이름 복원/정렬/손상 표시는 archive_zip이 한다.
"""
from __future__ import annotations

import os
import struct
import zipfile
import zlib
from typing import List, Optional

_LOCAL = b"PK\x03\x04"
_DESCRIPTOR = b"PK\x07\x08"
_CENTRAL = b"PK\x01\x02"
_CHUNK = 1024 * 1024
_FLAG_DESCRIPTOR = 0x8
_FLAG_UTF8 = 0x800
STORED, DEFLATED = 0, 8


class RecoveredInfo(zipfile.ZipInfo):
    __slots__ = ("data_offset", "truncated")


class _Entry:
    """open()이 돌려주는 읽기용 객체 - 압축을 풀면서 조금씩 돌려준다. 끝까지 정상이 아니면 EOFError(또는 zlib.error)를 낸다."""

    def __init__(self, fobj, info: RecoveredInfo):
        self._f = fobj
        self._info = info
        self._left = info.compress_size            # 읽을 압축 데이터 남은 양
        self._pos = info.data_offset
        self._dec = zlib.decompressobj(-15) if info.compress_type == DEFLATED else None
        self._done = False

    def read(self, n: int = -1) -> bytes:
        if self._done:
            return b""
        want = _CHUNK if n is None or n < 0 else n
        while True:
            raw = b""
            if self._left > 0:
                self._f.seek(self._pos)
                raw = self._f.read(min(self._left, _CHUNK))
                self._pos += len(raw)
                self._left -= len(raw)
            if self._dec is None:                    # stored
                if raw:
                    return raw[:want] if len(raw) <= want else self._unread(raw, want)
                self._done = True
                if self._info.truncated:
                    raise EOFError("압축 파일이 여기서 끊겼습니다")
                return b""
            out = self._dec.decompress(raw) if raw else b""
            if out:
                return out
            if self._dec.eof:
                self._done = True
                return b""
            if not raw:                              # 데이터가 모자란데 deflate가 끝나지 않음 = 잘림
                self._done = True
                raise EOFError("압축 파일이 여기서 끊겼습니다")

    def _unread(self, raw: bytes, want: int) -> bytes:
        extra = len(raw) - want                      # 요청보다 많이 읽은 만큼 되돌린다
        self._pos -= extra
        self._left += extra
        return raw[:want]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class RecoveredZip:
    """zipfile.ZipFile의 읽기 전용 대용품 (infolist/open/close)."""

    def __init__(self, path: str, infos: List[RecoveredInfo]):
        self._path = path
        self._infos = infos
        self._f = open(path, "rb")

    def infolist(self) -> List[RecoveredInfo]:
        return list(self._infos)

    def open(self, info: RecoveredInfo) -> _Entry:
        if info.compress_type not in (STORED, DEFLATED):
            raise NotImplementedError(f"지원하지 않는 압축 방식({info.compress_type})")
        return _Entry(self._f, info)

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _zip64_sizes(extra: bytes, usize: int, csize: int):
    """로컬 헤더 extra의 zip64 항목(0x0001)에서 실제 크기를 읽는다(4바이트 크기가 0xFFFFFFFF일 때)."""
    i = 0
    while i + 4 <= len(extra):
        tag, size = struct.unpack("<HH", extra[i:i + 4])
        body = extra[i + 4:i + 4 + size]
        if tag == 1:
            k = 0
            if usize == 0xFFFFFFFF and len(body) >= k + 8:
                usize = struct.unpack("<Q", body[k:k + 8])[0]
                k += 8
            if csize == 0xFFFFFFFF and len(body) >= k + 8:
                csize = struct.unpack("<Q", body[k:k + 8])[0]
        i += 4 + size
    return usize, csize


def _find_deflate_end(f, start: int, size: int):
    """deflate 데이터가 start에서 어디까지인지 찾는다. (압축 데이터 길이, 정상 종료 여부)."""
    dec = zlib.decompressobj(-15)
    pos, fed = start, 0
    while pos < size:
        f.seek(pos)
        chunk = f.read(min(_CHUNK, size - pos))
        if not chunk:
            break
        pos += len(chunk)
        try:
            dec.decompress(chunk)
        except zlib.error:
            return fed + len(chunk), False           # 중간에서 깨짐 - 여기까지를 이 항목으로 본다
        if dec.eof:
            return fed + len(chunk) - len(dec.unused_data), True
        fed += len(chunk)
    return fed, False


def _read_descriptor(f, pos: int, size: int):
    """데이터 바로 뒤의 데이터 설명자를 읽어 (crc, 압축크기, 원본크기, 설명자 길이). 없거나 이상하면 None."""
    f.seek(pos)
    buf = f.read(28)
    off = 4 if buf[:4] == _DESCRIPTOR else 0
    if len(buf) < off + 12:
        return None
    crc, c32, u32 = struct.unpack("<III", buf[off:off + 12])
    nxt32 = buf[off + 12:off + 16]
    if nxt32[:2] == b"PK" or pos + off + 12 >= size:          # 4바이트 크기 형식(다음이 다른 헤더이거나 파일 끝)
        return crc, c32, u32, off + 12
    if len(buf) >= off + 20:
        crc, c64, u64 = struct.unpack("<IQQ", buf[off:off + 20])
        return crc, c64, u64, off + 20
    return crc, c32, u32, off + 12


def _find_stored_end(f, start: int, size: int):
    """크기를 나중에 적은 저장(stored) 항목의 끝: 설명자 서명(PK\\x07\\x08)을 찾아 그 앞까지의 길이가 설명자의 크기와 같은 곳."""
    pos = start
    tail = b""
    while pos < size:
        f.seek(pos)
        chunk = f.read(min(_CHUNK, size - pos))
        if not chunk:
            break
        buf = tail + chunk
        base = pos - len(tail)
        i = buf.find(_DESCRIPTOR)
        while i != -1:
            at = base + i
            d = _read_descriptor(f, at, size)
            if d and d[1] == at - start:
                return at - start, True
            i = buf.find(_DESCRIPTOR, i + 1)
        pos += len(chunk)
        tail = buf[-3:]
    return size - start, False


def scan(path: str) -> List[RecoveredInfo]:
    """파일을 앞에서부터 훑어 찾은 항목들(RecoveredInfo)을 돌려준다. 첫 헤더부터 zip이 아니면 빈 목록."""
    infos: List[RecoveredInfo] = []
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        pos = 0
        while pos + 30 <= size:
            f.seek(pos)
            head = f.read(30)
            if head[:4] != _LOCAL:
                break                                   # 목차(PK\x01\x02)나 알 수 없는 데이터 - 여기까지
            ver, flag, method, mtime, mdate, crc, csize, usize, nlen, elen = struct.unpack("<HHHHHIIIHH", head[4:30])
            raw_name = f.read(nlen)
            extra = f.read(elen)
            if len(raw_name) < nlen or len(extra) < elen:
                break                                   # 헤더 자체가 잘림
            usize, csize = _zip64_sizes(extra, usize, csize)
            data_off = pos + 30 + nlen + elen
            truncated = False
            desc_len = 0
            if flag & _FLAG_DESCRIPTOR and (csize == 0 or method == DEFLATED):
                if method == DEFLATED:
                    csize, complete = _find_deflate_end(f, data_off, size)
                elif method == STORED:
                    csize, complete = _find_stored_end(f, data_off, size)
                else:
                    csize, complete = size - data_off, False
                if complete:
                    d = _read_descriptor(f, data_off + csize, size)
                    if d:
                        crc, _, usize_d, desc_len = d
                        usize = usize_d
                    else:
                        complete = False
                truncated = not complete
            elif data_off + csize > size:
                csize = size - data_off
                truncated = True
            name = raw_name.decode("utf-8", "replace") if flag & _FLAG_UTF8 else raw_name.decode("cp437")
            info = RecoveredInfo(name)
            info.flag_bits = flag
            info.compress_type = method
            info.CRC = crc
            info.compress_size = csize
            info.file_size = usize
            info.header_offset = pos
            info.data_offset = data_off
            info.truncated = truncated
            infos.append(info)
            if truncated:
                break
            pos = data_off + csize + desc_len
    return infos


def open_recovered(path: str) -> Optional[RecoveredZip]:
    """복구해서 읽을 수 있는 항목이 하나라도 있으면 RecoveredZip, 아니면 None."""
    try:
        infos = scan(path)
    except OSError:
        return None
    return RecoveredZip(path, infos) if infos else None
