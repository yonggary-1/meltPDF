"""
meltPDF - 이미지 -> PDF 변환기 (용지 없이, 이미지 크기 그대로)

- 이미지/폴더 드래그 앤 드롭 -> 썸네일 목록(타일형/목록형), 마우스로 끌어서 순서 변경
- 기존 PDF 열어서 페이지 추가/삭제/순서변경 - 원본 페이지 내용(텍스트/벡터/이미지 해상도)은
  전혀 재인코딩하지 않고 그대로 유지, 화면 목록에 보여줄 작은 미리보기만 별도로 렌더링함
  (자세한 내용은 pdf_core.py 상단 설명 참고)

실행: python main.py
필요 패키지: pip install -r requirements.txt

파일 구성(기능 하나 = 파일 하나): README.md의 "소스 구성" 참고
"""
from __future__ import annotations

import tkinter as tk

import bug_report
from app_window import App
from config import HAS_DND, TkinterDnD


def main():
    bug_report.start()              # 활동 기록 + 충돌 기록 켜기, 지난번 비정상 종료 확인(bug_report.py)
    try:
        root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    except Exception:
        # tkinterdnd2 초기화 실패 시 드래그앤드롭 없이라도 프로그램은 뜨도록 폴백
        root = tk.Tk()
    app = App(root)
    bug_report.attach(root, app.state_summary)   # 화면 쪽 오류 -> 버그 리포트, 멈춤 감시, 지난번 비정상 종료 알림
    root.mainloop()
    bug_report.finish()             # 정상 종료 표시


if __name__ == "__main__":
    try:
        main()
    except Exception:
        bug_report.report_startup_failure()
        raise
