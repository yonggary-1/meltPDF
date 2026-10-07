"""
파일 불러오기 - 이미지/폴더/PDF를 목록에 추가한다 (버튼 대화상자 + 드래그앤드롭 + 백그라운드 읽기).
읽은 결과는 모델(doc_model)에 넣기만 하고, 화면 갱신은 모델 알림으로 다른 기능이 알아서 한다.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import pdf_core
from config import APP_TITLE, DND_FILES, HAS_DND
from doc_model import DocModel
from load_queue import LoadQueue
from status_bar import StatusBar


class FileLoader:
    def __init__(self, root: tk.Misc, model: DocModel, status: StatusBar, jobs: LoadQueue):
        self.root = root
        self.jobs = jobs
        self.model = model
        self.status = status
        # 다른 기능(책/압축 파일 등)이 "이 파일은 내가 처리할게"라고 끼어들 수 있는 자리.
        # path를 받아 처리했으면 True를 돌려주는 함수를 넣는다.
        self.extra_drop_handlers: list = []

    # ---------------------------------------------------------- 대화상자
    def add_images_dialog(self):
        paths = filedialog.askopenfilenames(
            title="이미지 선택",
            filetypes=[("이미지 파일", " ".join(f"*{e}" for e in sorted(pdf_core.IMAGE_EXTS)))],
        )
        if paths:
            self.model.note_source(Path(paths[0]).stem)
            self._load_images_async(list(paths))

    def add_folder_dialog(self):
        folder = filedialog.askdirectory(title="폴더 선택")
        if not folder:
            return
        paths = pdf_core.list_images_in_folder(folder)
        if not paths:
            messagebox.showinfo(APP_TITLE, "선택한 폴더에서 이미지 파일을 찾지 못했습니다.")
            return
        self.model.note_source(Path(folder).name)
        self._load_images_async(paths)

    def open_pdf_dialog(self):
        path = filedialog.askopenfilename(title="PDF 선택", filetypes=[("PDF 파일", "*.pdf")])
        if path:
            self.model.note_source(Path(path).stem)
            self._load_pdf_async(path)

    # ---------------------------------------------------------- 드래그앤드롭
    def register_drop_targets(self, widgets):
        """파일을 떨굴 수 있는 위젯으로 등록한다 (tkinterdnd2가 없으면 아무것도 안 함)."""
        if not HAS_DND:
            return
        for widget in widgets:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]

        # 넣은 순서를 지키기 위해, 이미지 파일들은 모아 뒀다가 다른 종류(PDF/책/폴더)를 만나기 직전에
        # 먼저 대기열에 넣는다.
        image_paths = []

        def flush_images():
            if image_paths:
                self._load_images_async(list(image_paths))
                image_paths.clear()

        for p in paths:
            p = p.strip("{}")
            if os.path.isdir(p):
                self.model.note_source(Path(p).name)
                image_paths.extend(pdf_core.list_images_in_folder(p))
            elif Path(p).suffix.lower() in pdf_core.IMAGE_EXTS:
                self.model.note_source(Path(p).stem)
                image_paths.append(p)
            else:
                flush_images()
                if any(handler(p) for handler in self.extra_drop_handlers):
                    continue
                if p.lower().endswith(".pdf"):
                    self.model.note_source(Path(p).stem)
                    self._load_pdf_async(p)
        flush_images()

    # ---------------------------------------------------------- 백그라운드 로딩(대량 파일 대비)
    # 작업은 공용 대기열(LoadQueue)에 넣은 순서대로 하나씩 처리되고, 결과도 그 순서대로 목록에 붙는다.
    def _load_images_async(self, paths):
        self.status.set(f"이미지 {len(paths)}개 불러오는 중...")

        def work():
            loaded = []
            errors = []
            for p in paths:
                try:
                    loaded.append(pdf_core.load_image_item(p))
                except Exception as e:
                    errors.append(f"{Path(p).name}: {e}")
            return loaded, errors

        def done(result, error):
            loaded, errors = result if result else ([], [str(error)])
            self.model.add(loaded)
            if errors:
                messagebox.showwarning(APP_TITLE, "일부 파일을 불러오지 못했습니다:\n" + "\n".join(errors))

        self.jobs.submit(work, done)

    def _load_pdf_async(self, path):
        self.status.set(f"PDF 여는 중: {Path(path).name}")

        def done(items, error):
            if error:
                messagebox.showerror(APP_TITLE, f"PDF를 여는 데 실패했습니다:\n{error}")
                self.status.refresh()
            else:
                self.model.add(items)

        self.jobs.submit(lambda: pdf_core.load_pdf_items(path), done)
