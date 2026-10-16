"""
"쪽 그대로 넣은 이유" 창 - [?]를 누르면 연다(v0.21.0, 사용자 요청).

보여 주는 것: 썸네일, 항목 이름과 원본(PDF 이름, 쪽 번호), 원인(이름, 설명, 이 쪽에서 찾은 자세한 내용), 해결 방법 버튼들.
해결 방법은 page_reasons.SOLUTIONS에 이유마다 하나씩 추가한다(논의하며 추가 - 아직 없으면 그렇게 안내).
"""
from __future__ import annotations

import io
import tkinter as tk
import tkinter.messagebox
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

import activity_log
import page_reasons

WRAP = 430
PREVIEW_WRAP = 220


def _preview_photo(win, sol, item):
    try:
        im = sol.preview(item)
        if im is None:
            return None
        return ImageTk.PhotoImage(im.convert("RGB"), master=win)
    except Exception as e:
        activity_log.log(f"미리보기 실패({sol.text}): {type(e).__name__}: {e}")
        return None


def open_dialog(root: tk.Misc, app, item) -> tk.Toplevel:
    reason = getattr(item, "pdf_reason", "")
    detail = getattr(item, "pdf_reason_detail", "")
    activity_log.log(f"[?] 쪽 그대로 넣은 이유 보기: {item.label} - {reason} {detail}".rstrip())
    win = tk.Toplevel(root)
    win.title("쪽 그대로 넣은 이유")
    win.transient(root)
    win.resizable(False, False)
    body = ttk.Frame(win, padding=14)
    body.pack(fill=tk.BOTH, expand=True)

    top = ttk.Frame(body)
    top.pack(fill=tk.X)
    try:
        with Image.open(io.BytesIO(item.thumb_bytes)) as im:
            im.thumbnail((110, 110))
            photo = ImageTk.PhotoImage(im.convert("RGB"), master=win)
        thumb = tk.Label(top, image=photo, bd=2, relief=tk.SOLID, highlightthickness=0)
        thumb.image = photo                          # 그림이 사라지지 않게 붙잡아 둔다
        thumb.pack(side=tk.LEFT, anchor="n", padx=(0, 12))
    except Exception:
        pass
    head = ttk.Frame(top)
    head.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="n")
    ttk.Label(head, text=item.label, font=("", 10, "bold"), wraplength=WRAP - 120).pack(anchor="w")
    if item.origin_pdf:
        ttk.Label(head, text=f"원본: {Path(item.origin_pdf).name} {item.origin_page_no}쪽",
                  foreground="#555555", wraplength=WRAP - 120).pack(anchor="w", pady=(2, 0))
    ttk.Label(head, text="이미지로 꺼내지 않고 쪽 그대로 넣었습니다(파란 테두리).\n"
                         "PDF로 내보내면 원본 쪽이 그대로 들어갑니다.",
              foreground="#555555", wraplength=WRAP - 120, justify="left").pack(anchor="w", pady=(6, 0))

    ttk.Separator(body).pack(fill=tk.X, pady=10)
    ttk.Label(body, text="원인: " + page_reasons.title(reason), font=("", 10, "bold")).pack(anchor="w")
    ttk.Label(body, text=page_reasons.explain(reason), wraplength=WRAP, justify="left").pack(anchor="w", pady=(4, 0))
    if detail:
        ttk.Label(body, text=detail, foreground="#555555", wraplength=WRAP, justify="left").pack(anchor="w", pady=(4, 0))

    ttk.Separator(body).pack(fill=tk.X, pady=10)
    ttk.Label(body, text="해결 방법", font=("", 10, "bold")).pack(anchor="w")
    sols = page_reasons.solutions(reason)
    if not page_reasons.SOLUTIONS.get(reason):
        ttk.Label(body, text="이 원인은 아직 쪽 그대로 두는 것 말고 다른 방법이 없습니다. 원인별로 하나씩 추가할 예정입니다.",
                  foreground="#555555", wraplength=WRAP, justify="left").pack(anchor="w", pady=(4, 0))
    if getattr(item, "pdf_kept", False):
        ttk.Label(body, text="지금은 \"쪽 그대로 두기\"로 정해 둔 상태입니다([✓]). 다른 방법을 고르면 바뀝니다.",
                  foreground="#163f7a", wraplength=WRAP, justify="left").pack(anchor="w", pady=(4, 0))
    def run(sol):
        activity_log.log(f"해결 방법 실행: {sol.text} ({item.label})")
        try:
            done = sol.handler(app, item)
        except Exception as e:                       # 해결 방법이 실패해도 창과 목록은 그대로
            activity_log.log(f"해결 방법 실패: {type(e).__name__}: {e}")
            tk.messagebox.showwarning("meltPDF", f"처리하지 못했습니다:\n{e}", parent=win)
            return
        if done:
            win.destroy()

    side_by_side = any(sol.preview is not None for sol in sols)
    row = ttk.Frame(body)
    row.pack(fill=tk.X, pady=(6, 0))
    for col, sol in enumerate(sols):
        if side_by_side:                             # 결과 모습을 나란히 보여 주고 고르게 한다
            cell = ttk.Frame(row, padding=(0, 0, 12, 0))
            cell.grid(row=0, column=col, sticky="n")
            pic = _preview_photo(win, sol, item)
            if pic is not None:
                lab = tk.Label(cell, image=pic, bd=1, relief=tk.SOLID)
                lab.image = pic
                lab.pack(anchor="w")
            ttk.Button(cell, text=sol.text, command=lambda s=sol: run(s)).pack(anchor="w", pady=(6, 0))
            ttk.Label(cell, text=sol.description, wraplength=PREVIEW_WRAP, justify="left",
                      foreground="#555555").pack(anchor="w", pady=(4, 0))
        else:
            line = ttk.Frame(body)
            line.pack(fill=tk.X, pady=(6, 0))
            ttk.Button(line, text=sol.text, command=lambda s=sol: run(s)).pack(side=tk.LEFT, anchor="n")
            ttk.Label(line, text=sol.description, wraplength=WRAP - 140, justify="left").pack(
                side=tk.LEFT, padx=(10, 0), anchor="w")

    ttk.Button(body, text="닫기", command=win.destroy).pack(anchor="e", pady=(14, 0))
    win.bind("<Escape>", lambda e: win.destroy())
    win.update_idletasks()
    try:                                             # 메인 창 가운데에
        x = root.winfo_rootx() + (root.winfo_width() - win.winfo_reqwidth()) // 2
        y = root.winfo_rooty() + (root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    except tk.TclError:
        pass
    win.focus_set()
    return win
