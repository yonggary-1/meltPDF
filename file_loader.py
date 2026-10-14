"""
파일 불러오기 - 이미지/폴더/PDF를 목록에 추가한다 (버튼 대화상자 + 드래그앤드롭 + 백그라운드 읽기).
읽은 결과는 모델(doc_model)에 넣기만 하고, 화면 갱신은 모델 알림으로 다른 기능이 알아서 한다.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import activity_log
import book_import
import damaged_image
import folder_ask
import folder_pick
import incremental_add
import load_report
import parallel_load
import pdf_core
import pdf_meta
import ui_mailbox
from config import APP_TITLE, DND_FILES, HAS_DND
from doc_model import DocModel
from load_queue import LoadCancelled, LoadQueue
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
        # (path, before)를 받아 처리했으면 True를 돌려주는 함수를 넣는다(before: 이 항목 앞에 넣음, None이면 끝).
        self.extra_drop_handlers: list = []
        # 끌어다 놓은 자리 -> 그 자리 뒤쪽 항목 id(그 앞에 넣음). 목록 중간 놓기 기능(file_drop_mark.py)이 채운다.
        self.drop_anchor = None

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
            activity_log.log("파일 열기/추가: " + activity_log.names(paths))
            self.handle_paths(list(paths))

    def add_folder_dialog(self):
        """[폴더 (이미지) 추가]: 작은 창에서 "서브 폴더도 전부" 여부를 고르고 폴더를 고른다."""
        folder_pick.open_folder_pick(self.root, self.settings, self._add_folder)

    def _add_folder(self, folder: str, recursive: bool):
        activity_log.log(f"폴더 (이미지) 추가: {Path(folder).name} (하위 폴더 {'포함' if recursive else '안 함'})")
        none_msg = ("선택한 폴더(하위 폴더 포함)에서 이미지 파일을 찾지 못했습니다." if recursive
                    else "선택한 폴더에서 이미지 파일을 찾지 못했습니다.")
        self.model.note_source(Path(folder).name, str(Path(folder).parent))
        self._load_folder_async(folder, recursive, none_msg)

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
        # 목록 중간에 놓았으면 그 자리(파란 막대가 보이던 곳)의 뒤쪽 항목 - 그 앞에 넣는다(file_drop_mark.py)
        before = self.drop_anchor(event) if self.drop_anchor is not None else None
        where = "끝" if before is None else (f"'{self.model.items[before].label}' 앞" if before in self.model.items else "?")
        target = "썸네일 영역" if getattr(event, "widget", None) is not self.root else "창"
        activity_log.log(f"끌어다 놓기({target}, 자리 {where}, 목록 {len(self.model.order)}장, 불러오는 중 {self.jobs.pending}개): "
                         + activity_log.names(paths))
        self.handle_paths([p.strip("{}") for p in paths], before)

    def handle_paths(self, paths, before=None):
        """끌어다 놓거나 [파일 열기/추가]로 고른 경로들을 종류대로 처리한다: 폴더(바로 안의 이미지), 이미지, PDF(쪽),
        압축/책 파일(extra_drop_handlers). 열 수 없는 형식은 건너뛰고 알린다.
        before(항목 id)를 주면 모두 그 항목 앞에 넣는다(놓은 순서 그대로). None이면 목록 끝."""
        # 넣은 순서를 지키기 위해, 이미지 파일들은 모아 뒀다가 다른 종류(PDF/책/폴더)를 만나기 직전에
        # 먼저 대기열에 넣는다.
        image_paths = []
        skipped = []

        def flush_images():
            if image_paths:
                self._load_images_async(list(image_paths), before=before)
                image_paths.clear()

        for p in paths:
            if os.path.isdir(p):
                flush_images()
                self._handle_dropped_folder(p, before)
            elif Path(p).suffix.lower() in pdf_core.IMAGE_EXTS:
                self.model.note_source(Path(p).stem, str(Path(p).parent))
                image_paths.append(p)
            else:
                flush_images()
                if any(handler(p, before) for handler in self.extra_drop_handlers):
                    continue
                if p.lower().endswith(".pdf"):
                    self.model.note_source(Path(p).stem, str(Path(p).parent))
                    self._load_pdf_async(p, before)
                else:
                    skipped.append(Path(p).name)
        flush_images()
        if skipped:
            shown = "\n".join(skipped[:20]) + (f"\n... 외 {len(skipped) - 20}개" if len(skipped) > 20 else "")
            messagebox.showinfo(APP_TITLE, "열 수 없는 형식이라 건너뛴 파일:\n" + shown)

    def _handle_dropped_folder(self, folder: str, before=None):
        """끌어다 놓은 폴더: (1) 이미지도 하위 폴더도 없음 -> 아무것도 안 함, (2) 이미지만 있음 -> 바로 불러옴,
        (3) 이미지 없이 하위 폴더만 -> "이미지가 없습니다. 서브 폴더를 검색할까요?" [검색]/[취소],
        (4) 이미지와 하위 폴더 모두 -> "이미지가 X장 있습니다. 서브 폴더를 검색할까요?" [검색]/[확인](바로 안의 X장만)."""
        try:
            top = pdf_core.list_images_in_folder(folder)
            subs = _has_subfolders(folder)
        except OSError as e:
            messagebox.showinfo(APP_TITLE, f"폴더를 읽을 수 없습니다:\n{folder}\n({e})")
            return
        if not top and not subs:
            return
        choice = folder_ask.TOP_ONLY
        if subs:
            choice = folder_ask.ask(self.root, Path(folder).name, len(top))
        activity_log.log(f"폴더 {Path(folder).name}: 바로 안 {len(top)}장, 하위 폴더 {'있음' if subs else '없음'} -> {choice}")
        if choice == folder_ask.CANCEL:
            return
        self.model.note_source(Path(folder).name, str(Path(folder).parent))
        if choice == folder_ask.SEARCH:
            self._load_folder_async(folder, True, "서브 폴더에서도 이미지 파일을 찾지 못했습니다.", before)
        else:
            self._load_images_async(top, before=before)

    # ---------------------------------------------------------- 백그라운드 로딩(대량 파일 대비)
    # 작업은 공용 대기열(LoadQueue)에 넣은 순서대로 하나씩 처리되고, 결과도 그 순서대로 목록에 붙는다.
    def _load_images_async(self, paths, labels=None, before=None):
        """labels: 목록에 보일 이름(없으면 파일 이름). before: 이 항목 앞에 넣는다(None이면 끝)."""
        self.status.set(f"이미지 {len(paths)}개 불러오는 중...")
        labels = list(labels) if labels else [Path(p).name for p in paths]
        self.jobs.submit(lambda: self._load_paths(paths, labels, before), self._done_loading,
                         label=f"이미지 {len(paths)}장")

    def _load_folder_async(self, folder: str, recursive: bool, none_msg: str = "", before=None):
        """폴더 안 이미지 찾기(하위 폴더가 많으면 오래 걸릴 수 있음)부터 불러오기까지 일꾼 스레드에서 한다."""
        self.status.set("폴더에서 이미지 찾는 중...")

        def work():
            paths = pdf_core.list_images_in_folder(folder, recursive=recursive, should_stop=self.jobs.cancelled)
            if self.jobs.cancelled():
                r = LoadResult()
                r.cancelled = True
                return r
            # 하위 폴더까지 넣으면 이름이 겹칠 수 있어(1권/001.jpg, 2권/001.jpg) 목록 이름을 폴더 기준 상대 경로로 한다(압축 파일과 같은 방식)
            labels = [Path(p).relative_to(folder).as_posix() for p in paths] if recursive else [Path(p).name for p in paths]
            return self._load_paths(paths, labels, before)

        def done(result, error):
            if isinstance(error, LoadCancelled):
                self.status.refresh()
                return
            if result is not None and not result.items and not result.errors and none_msg and not result.cancelled:
                messagebox.showinfo(APP_TITLE, none_msg)
                self.status.refresh()
                return
            self._done_loading(result, error)

        self.jobs.submit(work, done, label=f"폴더 {Path(folder).name}" + (" +하위" if recursive else ""))

    def _load_paths(self, paths, labels, before=None) -> LoadResult:
        """(일꾼 스레드) 이미지 파일들을 목록 항목으로 읽는다. 여러 장을 동시에 읽고(parallel_load), 읽은 순서가 아니라
        넣은 순서대로 몇십 장씩 목록에 먼저 넣는다(incremental_add). 진행 상황은 상태 표시줄에 "n/전체"로 알린다.
        돌려주는 결과의 items는 이미 목록에 들어간 것이다(완료 처리에서는 다시 넣지 않고 개수와 알림에만 쓴다)."""
        result = LoadResult()
        total = len(paths)
        feed = incremental_add.Feeder(self.root, self.model, self.status, before=before)
        jobs = list(zip(paths, labels))
        n = 0
        try:
            for (_p, label), got, err in parallel_load.ordered(_read_one, jobs, should_stop=self.jobs.cancelled):
                n += 1
                if err is not None:
                    result.errors.append(f"{label}: {damaged_image.unreadable_reason(err)}")
                else:
                    item, damaged = got
                    result.items.append(item)
                    if damaged:
                        result.damaged.append(label)
                    feed.progress_text = f"이미지 불러오는 중... {n}/{total}"
                    feed.push(item)
                if n % 10 == 0 or n == total:
                    ui_mailbox.post(lambda n=n: self.status.set(f"이미지 불러오는 중... {n}/{total}"))
        finally:
            feed.finish()
        if n < total and self.jobs.cancelled():         # [중단]: 그때까지 읽은 이미지만 넣는다
            result.cancelled = True
        return result

    def _done_loading(self, result, error):
        if isinstance(error, LoadCancelled):         # [중단]으로 시작도 하지 않은 작업
            self.status.refresh()
            return
        if result is None:                           # 예상치 못한 오류(읽은 만큼은 이미 목록에 들어가 있다)
            result = LoadResult(errors=[str(error)])
        self.status.refresh()
        if result.cancelled:
            self.status.set(f"불러오기를 중단했습니다. ({len(result.items)}장 불러옴)")
        load_report.show(result)

    def _load_pdf_async(self, path, before=None):
        self.status.set(f"PDF 여는 중: {Path(path).name}")

        def work():
            items = pdf_core.load_pdf_items(path)
            return items, (pdf_meta.read_pdf_meta(path, Path(path).name) if items else None)

        def done(result, error):
            if isinstance(error, LoadCancelled):           # [중단]으로 시작도 하지 않은 작업
                self.status.refresh()
                return
            if error:
                messagebox.showerror(APP_TITLE, f"PDF를 여는 데 실패했습니다:\n{error}")
                self.status.refresh()
            else:
                items, meta = result
                self.model.offer_meta(meta)        # PDF의 서지 정보(문서 정보/XMP)
                self.model.add(items, before=before)
                self.status.refresh()                  # 쪽이 하나도 없어 목록 알림이 없을 때도 "PDF 여는 중"을 지운다

        self.jobs.submit(work, done, label=f"PDF {Path(path).name}")


def _read_one(job):
    """(동시 처리 스레드) 이미지 한 장 읽기 -> (항목, 손상 여부). 정상으로 못 읽으면(잘렸거나 일부가 깨짐)
    읽을 수 있는 부분만이라도 불러온다. 그것도 안 되면 원래 오류를 낸다."""
    path, label = job
    try:
        item = pdf_core.load_image_item(path)
        item.label = label
        return item, False
    except Exception as e:
        try:
            bad = damaged_image.load_damaged_item(label, path=path)
        except Exception:
            raise e
        bad.damaged = True
        return bad, True


def _has_subfolders(folder: str) -> bool:
    """하위 폴더가 하나라도 있는가(맥의 __MACOSX와 이름이 점으로 시작하는 숨김 폴더는 빼고)."""
    with os.scandir(folder) as it:
        for entry in it:
            try:
                if entry.is_dir() and entry.name != "__MACOSX" and not entry.name.startswith("."):
                    return True
            except OSError:
                continue
    return False
