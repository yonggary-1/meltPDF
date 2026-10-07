"""
책/압축 파일 열기 - zip/cbz 같은 파일에서 이미지만 뽑아 목록에 추가한다(화면 쪽 연결 담당).
실제로 파일을 읽는 일은 book_import.py와 각 포맷 파일(archive_zip.py 등)이 하고, 여기는
파일 선택 창 + 드래그앤드롭 받기 + 백그라운드 실행 + 진행 표시 + 오류 안내만 한다.

여러 파일을 한꺼번에 넣으면 넣은 순서대로 하나씩 처리하고, 각 파일의 이미지는 그 파일에
저장된 순서대로 이어 붙는다.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Tuple

import book_import
import pdf_core
import storage_policy
from book_common import BookError
from config import APP_TITLE
from doc_model import DocModel
from load_queue import LoadQueue
from settings import Settings
from status_bar import StatusBar


class BookLoader:
    def __init__(self, root: tk.Misc, model: DocModel, status: StatusBar, jobs: LoadQueue,
                 settings: Settings):
        self.root = root
        self.model = model
        self.status = status
        self.jobs = jobs
        self.settings = settings
        self._pending_ram = 0          # 대기열에서 처리를 기다리는 동안 메모리에 올라올 예정인 양

    # ---------------------------------------------------------- 들어오는 길
    def open_dialog(self):
        exts = " ".join(f"*{e}" for e in book_import.SUPPORTED_EXTS)
        paths = filedialog.askopenfilenames(
            title="압축/책 파일 선택 (이미지만 꺼냅니다)",
            filetypes=[("압축/책 파일", exts), ("모든 파일", "*.*")],
        )
        for p in paths:
            self._enqueue(p)

    def handle_drop(self, path: str) -> bool:
        """드래그앤드롭으로 들어온 파일이 내가 처리할 형식이면 받아 가고 True를 돌려준다."""
        if os.path.isfile(path) and book_import.is_supported(path):
            self._enqueue(path)
            return True
        return False

    def _enqueue(self, path: str):
        name = Path(path).name
        estimate = book_import.estimate_image_bytes(path)
        # 메모리에 둘지 디스크에 둘지: 기본은 메모리, 너무 크면 사용자에게 묻는다(설정에서 바꿀 수 있음)
        choice = storage_policy.choose(estimate, self.model.ram_bytes() + self._pending_ram,
                                       self.settings, self._ask_use_disk)
        if choice is None:
            self.status.set(f"{name}: 불러오지 않았습니다.")
            return
        to_ram = choice == storage_policy.RAM
        if to_ram:
            self._pending_ram += estimate
        self.model.note_source(Path(path).stem)
        self.status.set(f"{name} 대기 중...")
        self.jobs.submit(lambda: self._extract(path, name, to_ram),
                         lambda result, error: self._finish_one(result, error, estimate if to_ram else 0))

    def _ask_use_disk(self, estimate: int, limit: int) -> bool:
        return messagebox.askyesno(
            APP_TITLE,
            f"이 파일의 이미지는 압축을 풀면 약 {_fmt_size(estimate)}입니다.\n"
            f"메모리 한도(약 {_fmt_size(limit)})를 넘어서, 전부 메모리에 올리면 컴퓨터가 느려지거나 "
            f"멈출 수 있습니다.\n\n"
            f"디스크의 임시 폴더를 사용해서 불러올까요?\n"
            f"('아니요'를 누르면 이 파일은 불러오지 않습니다. 설정에서 기본 동작을 바꿀 수 있습니다.)")

    # ---------------------------------------------------------- 백그라운드 처리 (일꾼 스레드)
    def _extract(self, path: str, name: str, to_ram: bool) -> Tuple[List[pdf_core.PageItem], List[str]]:
        items: List[pdf_core.PageItem] = []
        errors: List[str] = []
        try:
            def progress(done: int, total: int):
                if done == total or done % 5 == 0:
                    self.root.after(0, lambda: self.status.set(
                        f"{name}에서 이미지 꺼내는 중... {done}/{total}"))

            extracted = book_import.extract_images(path, progress, to_ram)
            if not extracted:
                errors.append(f"{name}: 이미지가 들어 있지 않습니다.")
            for n, ex in enumerate(extracted, start=1):
                try:
                    if ex.data is not None:
                        item = pdf_core.load_image_item_from_bytes(ex.data, ex.label)
                    else:
                        item = pdf_core.load_image_item(ex.path)
                    item.label = ex.label          # 임시 파일 이름이 아니라 안에서의 원래 이름
                    ex.data = None                 # 메모리 사본을 일찍 놓아준다(항목이 필요한 만큼만 들고 있음)
                    items.append(item)
                except Exception as e:
                    errors.append(f"{name} / {ex.label}: 이미지를 읽지 못했습니다 ({e})")
                if n % 5 == 0:
                    self.root.after(0, lambda n=n, t=len(extracted): self.status.set(
                        f"{name} 썸네일 만드는 중... {n}/{t}"))
        except BookError as e:
            errors.append(f"{name}: {e}")
        return items, errors

    # ---------------------------------------------------------- 결과 처리 (화면 스레드)
    def _finish_one(self, result, error, reserved_ram: int = 0):
        self._pending_ram = max(0, self._pending_ram - reserved_ram)
        items, errors = result if result else ([], [f"예상치 못한 오류: {error}"])
        self.model.add(items)            # 완료 시 화면과 상태 표시줄이 모델 알림으로 갱신된다
        if errors:
            messagebox.showwarning(APP_TITLE, "일부를 불러오지 못했습니다:\n" + "\n".join(errors[:20])
                                   + (f"\n... 외 {len(errors) - 20}건" if len(errors) > 20 else ""))


def _fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f}GB"
    return f"{n / 1024 ** 2:.0f}MB"
