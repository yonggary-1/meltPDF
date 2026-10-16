"""
PDF 불러오기 - 쪽마다 "이미지 한 장을 놓은 쪽"이면 그 이미지를 꺼내 이미지 항목으로, 아니면 쪽 그대로 넣는다
(v0.20.1, 사용자 요청. 판정은 pdf_page_image.py). 이전에는 모든 쪽을 쪽 그대로 넣었다.

- 꺼낸 이미지는 책/압축 파일과 같은 규칙으로 메모리 또는 디스크 임시 폴더에 둔다(storage_policy - 한도를 넘으면 묻는다).
- 읽은 만큼 몇십 쪽씩 목록에 먼저 넣고(incremental_add), [중단]을 누르면 그때까지 읽은 쪽만 넣는다.
- 꺼낸 이미지를 이미지로 읽지 못하면(이미지 라이브러리가 모르는 형식 등) 그 쪽은 쪽 그대로 넣는다.
- 끝나면 상태 줄과 작업 기록에 "이미지로 꺼낸 쪽 N, 쪽 그대로 M"을 남긴다.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import List

import fitz  # PyMuPDF

import activity_log
import disk_ask
import incremental_add
import load_report
import parallel_load
import pdf_core
import pdf_meta
import pdf_page_image
import storage_policy
import temp_store
import ui_mailbox
from doc_model import DocModel
from load_queue import LoadCancelled, LoadQueue
from load_report import LoadResult
from status_bar import StatusBar


class PdfLoader:
    def __init__(self, root: tk.Misc, model: DocModel, status: StatusBar, jobs: LoadQueue, settings=None):
        self.root = root
        self.model = model
        self.status = status
        self.jobs = jobs
        self.settings = settings
        self._pending_ram = 0

    def load(self, path: str, before=None):
        name = Path(path).name
        to_ram = True
        estimate = 0
        if self.settings is not None:
            estimate = pdf_page_image.estimate_bytes(path)
            choice = storage_policy.choose(estimate, self.model.ram_bytes() + self._pending_ram,
                                           self.settings, disk_ask.ask)
            if choice is None:
                self.status.set(f"{name}: 불러오지 않았습니다.")
                return
            to_ram = choice == storage_policy.RAM
        reserved = estimate if to_ram else 0
        self._pending_ram += reserved
        self.status.set(f"PDF 여는 중: {name}")
        activity_log.log(f"PDF {name}: 꺼낼 이미지 {'메모리' if to_ram else '디스크'}, 예상 {estimate / 1024 ** 2:.0f}MB")
        self.jobs.submit(lambda: self._read(path, name, to_ram, before),
                         lambda result, error: self._done(result, error, reserved),
                         label=f"PDF {name}")

    # ---------------------------------------------------------- 일꾼 스레드
    def _read(self, path: str, name: str, to_ram: bool, before) -> LoadResult:
        items: List[pdf_core.PageItem] = []
        meta = pdf_meta.read_pdf_meta(path, name)
        doc = fitz.open(path)
        as_image = 0
        cancelled = False
        try:
            extract_ok = pdf_page_image.can_extract(doc)
            feed = incremental_add.Feeder(self.root, self.model, self.status,
                                          before_first=lambda m=meta: self.model.offer_meta(m), before=before)
            total = doc.page_count

            def pages():                          # (이 일꾼 스레드에서) 쪽마다 판정하고, 이미지 한 장뿐이면 그 바이트를 꺼낸다
                for i in range(total):
                    yield i, (pdf_page_image.classify(doc, doc[i]) if extract_ok
                              else pdf_page_image.Result(reason="locked"))

            n = 0
            try:
                # 꺼낸 이미지의 썸네일은 여러 장을 동시에 만들고, 쪽 순서대로 받는다(PDF 문서는 이 스레드에서만 다룬다)
                for (i, got), item, _err in parallel_load.ordered(
                        lambda job: self._image_item(job[1], name, job[0], total, to_ram), pages(),
                        should_stop=self.jobs.cancelled):
                    n += 1
                    if item is None:
                        item = pdf_core.pdf_page_item(doc, doc[i], path, i)
                        # 쪽 그대로 넣은 이유(v0.21.0) - 파란 테두리와 [?] 창에서 보여 준다(page_reasons.py)
                        item.pdf_reason = got.reason if got.data is None else "read_fail"
                        item.pdf_reason_detail = got.detail if got.data is None else "꺼낸 이미지를 이미지로 읽지 못했습니다."
                    else:
                        as_image += 1
                    items.append(item)
                    feed.progress_text = f"{name} 읽는 중... {n}/{total}"
                    feed.push(item)
                    if n % 5 == 0:
                        ui_mailbox.post(lambda k=n: self.status.set(f"{name} 읽는 중... {k}/{total}"))
            finally:
                feed.finish()
            cancelled = n < total and self.jobs.cancelled()
        finally:
            doc.close()
        activity_log.log(f"PDF {name}: {len(items)}쪽 - 이미지로 꺼냄 {as_image}, 쪽 그대로 {len(items) - as_image}"
                         + (", 중단됨" if cancelled else ""))
        r = LoadResult(items, [], [], name, [], meta if items else None)
        r.cancelled = cancelled
        r.as_image = as_image
        return r

    @staticmethod
    def _image_item(got, name: str, index: int, page_count: int, to_ram: bool):
        """(동시 처리 스레드) 판정 결과(pdf_page_image.Result)로 만든 이미지 항목. 꺼낸 것이 없거나 이미지로 읽지 못하면 None(쪽 그대로).
        항목은 PDF에서처럼 보이게: 원본 바이트 그대로 + 돌려 놓인 방향(rotate), 원본의 EXIF 회전은 따르지 않음(pdf_core.load_fixed_image_item)."""
        if got.data is None:
            return None
        data, ext = got.data, got.ext
        label = f"{name} - p{index + 1}{ext}"
        try:
            if to_ram:
                item = pdf_core.load_fixed_image_item(label, got.rotate, data=data)
            else:
                tmp = temp_store.new_path(ext)
                with open(tmp, "wb") as f:
                    f.write(data)
                item = pdf_core.load_fixed_image_item(label, got.rotate, path=tmp)
            item.label = label
            item.pdf_page_count = page_count         # 이미지 내보내기 이름의 쪽 번호 자릿수(PDF 쪽과 같게)
            return item
        except Exception:
            return None

    # ---------------------------------------------------------- 화면 스레드
    def _done(self, result, error, reserved: int):
        self._pending_ram = max(0, self._pending_ram - reserved)
        if isinstance(error, LoadCancelled):              # [중단]으로 시작도 하지 않은 작업
            self.status.refresh()
            return
        if error is not None or result is None:
            result = LoadResult(errors=[f"PDF를 여는 데 실패했습니다: {error}"])
        self.status.refresh()
        if result.cancelled:
            self.status.set(f"불러오기를 중단했습니다. ({len(result.items)}쪽 불러옴)")
        elif result.items:
            n, k = len(result.items), getattr(result, "as_image", 0)
            self.status.set(f"{result.source}: {n}쪽 중 {k}쪽은 이미지로 꺼냈고, {n - k}쪽은 쪽 그대로 넣었습니다.")
        load_report.show(result)
