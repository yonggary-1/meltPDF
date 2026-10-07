"""
메인 창 조립 - 각 기능 객체를 만들어 연결하고, 툴바/하단바의 버튼을 배치한다.
여기에는 기능 로직을 넣지 않는다. 새 기능은 자기 파일에 만들고, 여기서는 만든 뒤
버튼 한 줄(toolbar.add)만 추가한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from book_loader import BookLoader
from config import HAS_DND, WINDOW_TITLE
from doc_model import DocModel
from drag_reorder import DragReorder
from export import Exporter
from file_loader import FileLoader
from key_nav import KeyNav
from load_queue import LoadQueue
from page_actions import PageActions
from rename_pages import RenamePages
from selection import Selection
from settings import Settings
from settings_dialog import SettingsDialog
from status_bar import StatusBar
from tile_view import TileView
from wrapbar import WrapBar


class App:
    def __init__(self, root: tk.Misc):
        self.root = root
        root.title(WINDOW_TITLE)
        root.geometry("960x640")
        root.minsize(760, 480)

        # 위젯을 만드는(=pack하는) 순서가 곧 화면 배치 순서다: 툴바, 안내문, 하단바, 그 다음 가운데 영역.
        # (가운데 영역은 expand라서 하단바보다 먼저 pack하면 하단바 자리가 사라진다)
        self.model = DocModel()
        self.settings = Settings()
        self.toolbar = WrapBar(root, pad=6, gap_x=4, gap_y=4)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        self.hint_label = self._build_hint()
        self.status = StatusBar(root, self.model)
        self.view = TileView(root, self.model)
        self.view.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(4, 0))

        self.selection = Selection(self.view, self.model)
        self.keynav = KeyNav(self.view, self.model)
        self.drag = DragReorder(root, self.view, self.model)
        self.jobs = LoadQueue(root)        # 불러오기 작업을 넣은 순서대로 처리하는 공용 대기열
        self.loader = FileLoader(root, self.model, self.status, self.jobs)
        self.books = BookLoader(root, self.model, self.status, self.jobs, self.settings)
        self.loader.extra_drop_handlers.append(self.books.handle_drop)
        self.renamer = RenamePages(root, self.model)
        self.settings_dialog = SettingsDialog(root, self.settings)
        self.actions = PageActions(self.view.canvas, self.model)
        self.exporter = Exporter(root, self.model, self.status)

        self._fill_toolbar()
        self._fill_bottom_bar()
        self.loader.register_drop_targets((self.view.canvas, self.hint_label, root))

    def _build_hint(self) -> ttk.Label:
        hint = "이미지 파일이나 폴더를 아래로 드래그하세요. (zip/cbz는 안의 이미지만 꺼내고, PDF는 페이지로 열립니다 / 썸네일을 눌러서 끌면 순서를 바꿀 수 있습니다)"
        if not HAS_DND:
            hint = "[드래그앤드롭 비활성 - tkinterdnd2 미설치] 위 버튼으로 이미지/폴더/PDF를 추가하세요. (썸네일을 눌러서 끌면 순서를 바꿀 수 있습니다)"
        label = ttk.Label(self.root, text=hint, padding=(8, 4))
        label.pack(side=tk.TOP, fill=tk.X)
        return label

    def _fill_toolbar(self):
        # 창 폭이 좁아지면 WrapBar가 알아서 다음 줄로 넘기므로, 버튼이 늘어도 add()만 추가하면 된다.
        tb = self.toolbar
        tb.add(ttk.Button(tb, text="이미지 추가", command=self.loader.add_images_dialog))
        tb.add(ttk.Button(tb, text="폴더 추가", command=self.loader.add_folder_dialog))
        tb.add(ttk.Button(tb, text="기존 PDF 열기(수정)", command=self.loader.open_pdf_dialog))
        tb.add(ttk.Button(tb, text="압축/책에서 이미지 추출", command=self.books.open_dialog))

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)

        tb.add(ttk.Button(tb, text="선택 항목 표지로 지정", command=self.actions.set_cover_selected))
        tb.add(ttk.Button(tb, text="표지 해제", command=self.actions.clear_cover))
        tb.add(ttk.Button(tb, text="파일명 순차 정렬", command=self.renamer.open_dialog), gap_before=8)

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)
        tb.add(ttk.Label(tb, text="보기:"))
        tb.add(ttk.Radiobutton(tb, text="타일형", value="grid",
                               variable=self.view.view_mode_var,
                               command=self.view.on_view_mode_change))
        tb.add(ttk.Radiobutton(tb, text="목록형", value="list",
                               variable=self.view.view_mode_var,
                               command=self.view.on_view_mode_change))

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)
        tb.add(ttk.Checkbutton(tb, text="드래그할 때 썸네일 따라다니기",
                               variable=self.drag.ghost_var))

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)
        tb.add(ttk.Button(tb, text="설정", command=self.settings_dialog.open))

    def _fill_bottom_bar(self):
        bar = self.status.frame
        # 삭제 버튼들은 실수로 누르기 쉬운 파괴적 동작이라 툴바가 아니라 하단바에 따로 모아둔다.
        danger = ttk.Frame(bar)
        danger.pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(danger, text="선택 삭제", command=self.actions.delete_selected).pack(side=tk.LEFT)
        ttk.Button(danger, text="전체 삭제", command=self.actions.delete_all).pack(
            side=tk.LEFT, padx=(4, 0))
        self.exporter.make_button(bar).pack(side=tk.RIGHT)
