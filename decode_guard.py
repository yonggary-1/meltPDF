"""
이미지 풀기 잠금 - 깨진 이미지 검출이 여러 장 동시 처리 때문에 빠져나가지 않게 한다(v0.19.6).

깨진 이미지를 "읽을 수 있는 데까지" 풀 때(damaged_image.open_tolerant)는 Pillow 전체에 걸리는 설정
(ImageFile.LOAD_TRUNCATED_IMAGES)을 잠깐 켠다. v0.18.0부터 썸네일을 여러 스레드가 동시에 만들면서, 그 순간 다른 스레드가
풀던 깨진 이미지가 오류 없이 통과해 손상 표시 없이 목록에 들어갔다(시험: 깨진 100장 중 33~40장이 통과).

그래서 읽기/쓰기 잠금을 둔다.
- 보통 이미지 풀기(pdf_core.load_image_item 등)는 shared(): 여럿이 동시에 해도 된다.
- 깨진 이미지 풀기는 exclusive(): 그동안 다른 풀기는 모두 기다리고, 다른 풀기가 끝나기를 기다린 뒤 시작한다.
- 깨진 이미지가 기다리는 중이면 새 보통 풀기는 그 뒤로 줄을 선다(깨진 이미지가 계속 밀리지 않게).
깨진 이미지가 없으면 잠금을 잡고 놓는 비용뿐이라 속도 차이는 거의 없다.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_cond = threading.Condition()
_readers = 0
_writer = False
_writers_waiting = 0


@contextmanager
def shared():
    global _readers
    with _cond:
        while _writer or _writers_waiting:
            _cond.wait()
        _readers += 1
    try:
        yield
    finally:
        with _cond:
            _readers -= 1
            if _readers == 0:
                _cond.notify_all()


@contextmanager
def exclusive():
    global _writer, _writers_waiting
    with _cond:
        _writers_waiting += 1
        try:
            while _writer or _readers:
                _cond.wait()
        finally:
            _writers_waiting -= 1
        _writer = True
    try:
        yield
    finally:
        with _cond:
            _writer = False
            _cond.notify_all()
