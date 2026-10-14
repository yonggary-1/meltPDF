"""
파일 불러오기 - 이미지/폴더/PDF를 목록에 추가한다 (버튼 대화상자 + 드래그앤드롭 + 백그라운드 읽기).
읽은 결과는 모델(doc_model)에 넣기만 하고, 화면 갱신은 모델 알림으로 다른 기능이 알아서 한다.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import book_import
import damaged_image
import folder_pick
import load_report
import pdf_core
import pdf_meta
from config import APP_TITLE, DND_FILES, HAS_DND
from doc_model import DocModel
from load_queue import LoadQueue
from load_report import LoadResult
from status_bar import StatusBar


class FileLoader:
    def __init__(self, root: tk.Misc, model: DocModel, status: StatusBar, jobs: LoadQueue, settings=None):
        self.root = root
        self.settings = settings
        self.jobs = jobs
        self.model = model
        self.status = status
        # 다른 기능(책/압축 파일 등)이 "이 파일은 내가 처리할게"라고 끼어들 수 있는 자리.
        # path를 받아 처리했으면 True를 돌려주는 함수를 넣는다.
        self.extra_drop_handlers: list = []

    # ---------------------------------------------------------- 대화상자
    def open_files_dialog(self):
        """[파일 열기/추가]: 이미지, PDF, 압축/책 파일을 한 번에 고른다. 고른 파일은 끌어다 놓은 것과 똑같이 처리한다."""
        images = " ".join(f"*{e}" for e in sorted(pdf_core.IMAGE_EXTS))
        books = " ".join(f"*{e}" for e in book_import.SUPPORTED_EXTS)
        paths = filedialog.askopenfilenames(
            title="파일 열기/추가",
            filetypes=[("열 수 있는 모든 파일", f"{images} *.pdf {books}"), ("이미지 파일", images),
                       ("PDF 파일", "*.pdf"), ("압축/책 파일", books), ("모든 파일", "*.*")],
        )
        if paths:
            self.handle_paths(list(paths))

    def add_folder_dialog(self):
        """[폴더 (이미지) 추가]: 작은 창에서 "서브 폴더도 전부" 여부를 고르고 폴더를 고른다."""
        folder_pick.open_folder_pick(self.root, self.settings, self._add_folder)

    def _add_folder(self, folder: str, recursive: bool):
        paths = pdf_core.list_images_in_folder(folder, recursive=recursive)
        if not paths:
            where = "선택한 폴더(하위 폴더 포함)" if recursive else "선택한 폴더"
            messagebox.showinfo(APP_TITLE, f"{where}에서 이미지 파일을 찾지 못했습니다.")
            return
        self.model.note_source(Path(folder).name, str(Path(folder).parent))
        # 하위 폴더까지 넣으면 이름이 겹칠 수 있어(1권/001.jpg, 2권/001.jpg) 목록 이름을 폴더 기준 상대 경로로 한다(압축 파일과 같은 방식)
        labels = [Path(p).relative_to(folder).as_posix() for p in paths] if recursive else None
        self._load_images_async(paths, labels)

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
        self.handle_paths([p.strip("{}") for p in paths])

    def handle_paths(self, paths):
        """끌어다 놓거나 [파일 열기/추가]로 고른 경로들을 종류대로 처리한다: 폴더(바로 안의 이미지), 이미지, PDF(쪽),
        압축/책 파일(extra_drop_handlers). 열 수 없는 형식은 건너뛰고 알린다."""
        # 넣은 순서를 지키기 위해, 이미지 파일들은 모아 뒀다가 다른 종류(PDF/책/폴더)를 만나기 직전에
        # 먼저 대기열에 넣는다.
        image_paths = []
        skipped = []

        def flush_images():
            if image_paths:
                self._load_images_async(list(image_paths))
                image_paths.clear()

        for p in paths:
            if os.path.isdir(p):
                self.model.note_source(Path(p).name, str(Path(p).parent))
                image_paths.extend(pdf_core.list_images_in_folder(p))
            elif Path(p).suffix.lower() in pdf_core.IMAGE_EXTS:
                self.model.note_source(Path(p).stem, str(Path(p).parent))
                image_paths.append(p)
            else:
                flush_images()
                if any(handler(p) for handler in self.extra_drop_handlers):
                    continue
                if p.lower().endswith(".pdf"):
                    self.model.note_source(Path(p).stem, str(Path(p).parent))
                    self._load_pdf_async(p)
                else:
                    skipped.append(Path(p).name)
        flush_images()
        if skipped:
            shown = "\n".join(skipped[:20]) + (f"\n... 외 {len(skipped) - 20}개" if len(skipped) > 20 else "")
            messagebox.showinfo(APP_TITLE, "열 수 없는 형식이라 건너뛴 파일:\n" + shown)

    # ---------------------------------------------------------- 백그라운드 로딩(대량 파일 대비)
    # 작업은 공용 대기열(LoadQueue)에 넣은 순서대로 하나씩 처리되고, 결과도 그 순서대로 목록에 붙는다.
    def _load_images_async(self, paths, labels=None):
        """labels: 목록에 보일 이름(없으면 파일 이름)."""
        self.status.set(f"이미지 {len(paths)}개 불러오는 중...")
        labels = list(labels) if labels else [Path(p).name for p in paths]

        def work():
            result = LoadResult()
            for p, label in zip(paths, labels):
                try:
                    item = pdf_core.load_image_item(p)
                    item.label = label
                    result.items.append(item)
                except Exception as e:
                    # 정상으로는 못 읽는 이미지(잘렸거나 일부가 깨짐): 읽을 수 있는 부분만이라도 불러온다
                    try:
                        bad = damaged_image.load_damaged_item(label, path=p)
                        bad.damaged = True
                        result.items.append(bad)
                        result.damaged.append(label)
                    except Exception:
                        result.errors.append(f"{label}: {damaged_image.unreadable_reason(e)}")
            return result

        def done(result, error):
            result = result if result else LoadResult(errors=[str(error)])
            self.model.add(result.items)
            load_report.show(result)

        self.jobs.submit(work, done)

    def _load_pdf_async(self, path):
        self.status.set(f"PDF 여는 중: {Path(path).name}")

        def work():
            items = pdf_core.load_pdf_items(path)
            return items, (pdf_meta.read_pdf_meta(path, Path(path).name) if items else None)

        def done(result, error):
            if error:
                messagebox.showerror(APP_TITLE, f"PDF를 여는 데 실패했습니다:\n{error}")
                self.status.refresh()
            else:
                items, meta = result
                self.model.offer_meta(meta)        # PDF의 서지 정보(문서 정보/XMP)
                self.model.add(items)

        self.jobs.submit(work, done)
