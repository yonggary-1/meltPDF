"""
메인 창 조립 - 각 기능 객체를 만들어 연결하고, 툴바/하단바의 버튼을 배치한다.
여기에는 기능 로직을 넣지 않는다. 새 기능은 자기 파일에 만들고, 여기서는 만든 뒤
버튼 한 줄(toolbar.add)만 추가한다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import app_icon
import ui_mailbox
from book_loader import BookLoader
from config import WINDOW_TITLE
from doc_model import DocModel
from damaged_nav import DamagedNav
from drag_reorder import DragReorder
from empty_hint import EmptyHint
from export import Exporter
from file_loader import FileLoader
from image_export_dialog import ImageExporter
from image_viewer import ImageViewer
from key_nav import KeyNav
from load_queue import LoadQueue
from file_drop_mark import FileDropMark
from load_stop import LoadStopButton
from meta_dialog import MetaDialog
from page_actions import PageActions
from ram_meter import RamMeter
from rename_pages import RenamePages
from selected_export import SelectedExporter
from selection import Selection
from settings import Settings
from settings_dialog import SettingsDialog
from status_bar import StatusBar
from tile_view import TileView
from wrapbar import WrapBar


SETTINGS_GAP = 40                  # 하단 [전체 이미지 내보내기]와 [설정] 사이 간격(px)

class App:
    def __init__(self, root: tk.Misc):
        self.root = root
        root.title(WINDOW_TITLE)
        app_icon.apply(root)               # 창 아이콘(액자 속 도장 모양) - assets/meltPDF.ico
        root.geometry("960x640")
        root.minsize(760, 480)

        # 위젯을 만드는(=pack하는) 순서가 곧 화면 배치 순서다: 툴바, 하단바, 그 다음 가운데 영역.
        # (가운데 영역은 expand라서 하단바보다 먼저 pack하면 하단바 자리가 사라진다)
        self.model = DocModel()
        self.settings = Settings()
        # 맨 위 줄: 왼쪽은 버튼 툴바(폭이 좁으면 여러 줄로 접힘), 오른쪽 위에는 큰 [PDF 내보내기] 버튼(창 폭과 상관없이 고정).
        self.top_bar = ttk.Frame(root)
        self.top_bar.pack(side=tk.TOP, fill=tk.X)
        self.pdf_box = ttk.Frame(self.top_bar)            # 큰 버튼 자리(높이 = 툴바 두 줄) - _fill_toolbar에서 채움
        self.pdf_box.pack(side=tk.RIGHT, anchor="n", padx=(6, 8), pady=6)
        self.toolbar = WrapBar(self.top_bar, pad=6, gap_x=4, gap_y=4)
        self.toolbar.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="n")
        self.status = StatusBar(root, self.model)
        self.view = TileView(root, self.model)
        self.view.frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(4, 0))

        self.selection = Selection(self.view, self.model)
        self.keynav = KeyNav(self.view, self.model)
        self.drag = DragReorder(root, self.view, self.model)
        self.viewer = ImageViewer(root, self.model, self.view)      # 썸네일 두 번 누름/Enter -> 원본 크기로 보는 창
        ui_mailbox.start(root)             # 일꾼 스레드 -> 화면 스레드 우편함(넘기는 쪽이 기다리지 않음)
        self.jobs = LoadQueue(root)        # 불러오기 작업을 넣은 순서대로 처리하는 공용 대기열
        self.empty_hint = EmptyHint(self.view.canvas, self.model, self.jobs)   # 목록이 비었을 때 가운데 안내(불러오는 중 표시 포함)
        self.loader = FileLoader(root, self.model, self.status, self.jobs, self.settings)
        self.books = BookLoader(root, self.model, self.status, self.jobs, self.settings)
        self.loader.extra_drop_handlers.append(self.books.handle_drop)
        self.renamer = RenamePages(root, self.model)
        self.settings_dialog = SettingsDialog(root, self.settings)
        self.meta_dialog = MetaDialog(root, self.model)
        self.actions = PageActions(self.view.canvas, self.model)
        self.exporter = Exporter(root, self.model, self.status)
        self.image_exporter = ImageExporter(root, self.model, self.status, self.settings)
        self.selected_exporter = SelectedExporter(root, self.model, self.status)

        self._fill_toolbar()
        self._fill_bottom_bar()
        self._limit_min_width()
        self.loader.register_drop_targets((self.view.canvas, root))
        # 목록에 이미지가 있을 때 밖에서 끌어온 파일: 파란 막대로 놓을 자리를 보여 주고 그 자리에 넣는다
        self.file_drop_mark = FileDropMark(self.view, self.model, self.loader)

    def _fill_toolbar(self):
        # 창 폭이 좁아지면 WrapBar가 알아서 다음 줄로 넘기므로, 버튼이 늘어도 add()만 추가하면 된다.
        tb = self.toolbar
        # 이미지/PDF/압축·책 파일은 [파일 열기/추가] 하나로 연다(끌어다 놓기와 같은 처리). 폴더는 윈도우 선택 창이 달라 따로 둔다.
        tb.add(ttk.Button(tb, text="파일 열기/추가", command=self.loader.open_files_dialog))
        tb.add(ttk.Button(tb, text="폴더 (이미지) 추가", command=self.loader.add_folder_dialog))

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)

        tb.add(ttk.Button(tb, text="선택 항목 표지로 지정", command=self.actions.set_cover_selected))
        tb.add(ttk.Button(tb, text="표지 해제", command=self.actions.clear_cover))
        tb.add(ttk.Button(tb, text="파일명 변경하기", command=self.renamer.open_dialog), gap_before=8)

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)
        # "보기:" 라벨과 라디오 버튼은 한 덩어리(프레임 하나)로 추가한다 - 줄바꿈될 때 중간에서
        # 갈라지지 않고 통째로 다음 줄로 내려가게 하려는 것.
        view_group = ttk.Frame(tb)
        ttk.Label(view_group, text="보기:").pack(side=tk.LEFT)
        for text, value in (("타일형", "grid"), ("목록형", "list")):
            ttk.Radiobutton(view_group, text=text, value=value, variable=self.view.view_mode_var,
                            command=self.view.on_view_mode_change).pack(side=tk.LEFT, padx=(6, 0))
        tb.add(view_group)

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)
        tb.add(ttk.Checkbutton(tb, text="드래그할 때 썸네일 따라다니기",
                               variable=self.drag.ghost_var))

        tb.add(ttk.Separator(tb, orient=tk.VERTICAL), gap_before=8)
        tb.add(ttk.Button(tb, text="서지 정보(Metadata)", command=self.meta_dialog.open))
        self._fill_pdf_box()

    def _limit_min_width(self):
        """창 가로 폭의 최저치: 툴바가 세 줄이 되지 않는 폭(큰 [PDF 내보내기] 버튼 자리 포함)과 하단 버튼 줄이 잘리지 않는 폭 중
        큰 것(v0.19.5). 버튼 폭은 글꼴과 화면 배율마다 달라 실제 크기로 잰다."""
        self.root.update_idletasks()
        box = self.pdf_box.winfo_reqwidth() + 6 + 8                  # 큰 버튼 + 좌우 여백(pack padx)
        top_w = self.toolbar.min_width_for_rows(2) + box
        bottom_w = self.status.frame.winfo_reqwidth()
        min_w = max(top_w, bottom_w)
        self.root.minsize(min_w, 480)
        if self.root.winfo_width() > 1 and self.root.winfo_width() < min_w:
            self.root.geometry(f"{min_w}x{max(self.root.winfo_height(), 480)}")

    def _fill_pdf_box(self):
        """오른쪽 위 큰 [PDF 내보내기] 버튼: 높이는 툴바 두 줄(버튼 두 개 높이 + 줄 간격), 폭은 글자에 맞춤.
        툴바 오른쪽에 먼저 자리를 잡아 두므로 창 폭을 줄여도 항상 오른쪽 위에 그대로 있고, 툴바가 남은 폭에서 접힌다."""
        probe = ttk.Button(self.toolbar, text="가")    # 툴바 버튼 한 줄의 높이를 재는 용도(재고 바로 지움)
        row_h = probe.winfo_reqheight()
        probe.destroy()
        btn = self.exporter.make_button(self.pdf_box, big=True)
        self.pdf_box.configure(width=btn.winfo_reqwidth() + 24, height=row_h * 2 + 4)
        self.pdf_box.pack_propagate(False)
        btn.pack(fill=tk.BOTH, expand=True)
    def _fill_bottom_bar(self):
        bar = self.status.frame
        # 삭제 버튼들은 실수로 누르기 쉬운 파괴적 동작이라 툴바가 아니라 하단바에 따로 모아둔다.
        danger = ttk.Frame(bar)
        danger.pack(side=tk.LEFT)
        ttk.Button(danger, text="선택 삭제", command=self.actions.delete_selected).pack(side=tk.LEFT)
        ttk.Button(danger, text="전체 삭제", command=self.actions.delete_all).pack(
            side=tk.LEFT, padx=(4, 0))
        # 불러오는 중(목록에 이미 썸네일이 보일 때) [중단] - [전체 삭제] 옆
        self.load_stop = LoadStopButton(danger, self.model, self.jobs)
        # [깨진 이미지 N장] - 빨간 테두리 이미지를 차례로 찾아가는 버튼(삭제 버튼들과 내보내기 버튼 사이)
        self.damaged_nav = DamagedNav(bar, self.view, self.model, self.status, self.keynav)
        self.damaged_nav.button.pack(side=tk.LEFT, padx=(16, 0), fill=tk.Y)   # 높이를 옆 버튼들과 맞춘다
        # 메모리 미터는 윗줄(상태 문구 줄)의 오른쪽 끝에 둔다 - 아랫줄에 내보내기 버튼이 셋이라 좁은 창에서 잘리지 않게.
        self.ram_meter = RamMeter(self.status.top_row)
        self.ram_meter.frame.pack(side=tk.RIGHT, padx=(10, 0), before=self.status.label)
        # pack을 RIGHT로 하면 먼저 둔 것이 맨 오른쪽: [설정], (넓은 간격), 전체 이미지 내보내기, 선택된 이미지 내보내기 순
        # ([PDF 내보내기]는 오른쪽 위 큰 버튼으로, [설정]은 툴바에서 그 자리로 옮김 - v0.19.5.
        #  내보내기 버튼과 헷갈려 잘못 누르지 않게 [설정] 앞에 넓은 간격을 둔다)
        ttk.Button(bar, text="설정", command=self.settings_dialog.open).pack(side=tk.RIGHT)
        self.image_exporter.make_button(bar).pack(side=tk.RIGHT, padx=(0, SETTINGS_GAP))
        self.selected_exporter.make_button(bar).pack(side=tk.RIGHT, padx=(0, 6))

    def state_summary(self) -> str:
        """버그 리포트에 넣을 지금 상태(bug_report.py가 부름)."""
        m = self.model
        kinds = {}
        for it in m.items.values():
            kinds[it.kind] = kinds.get(it.kind, 0) + 1
        try:
            geo = self.root.winfo_geometry()
            scaling = float(self.root.tk.call("tk", "scaling"))
        except Exception:
            geo, scaling = "?", 0.0
        return (f"목록 {len(m.order)}장 {kinds} | 선택 {len(m.selected)} | 표지 {'있음' if m.cover_id else '없음'}"
                f" | 메모리에 든 원본 {m.ram_bytes() / 1024 ** 2:.0f}MB\n"
                f"불러오기 작업 대기/진행 {self.jobs.pending}개 (중단 표시 {self.jobs.cancelled()})"
                f" | 보기 {self.view.view_mode_var.get()} | 창 {geo} | tk scaling {scaling:.2f}")
