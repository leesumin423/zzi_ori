"""메모지(스티키 노트) 스타일의 업무 체크리스트 팝업.

tkinter 표준 라이브러리만 사용 (추가 설치 불필요, Windows 기본 python.org 설치본에는 기본 포함).
체크한 항목은 "완료 표시 저장하고 닫기" 버튼을 눌러야 저장된다 (core.state 로 넘김).

Windows 기본 Tk 글꼴은 컬러 이모지(🔴🟠🎉 등)를 지원하지 않아 깨진 네모/기호로 보이는 경우가 많아,
이모지 없이 한글 텍스트 + 색상만으로 구분한다.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import font as tkfont
from typing import Callable, Dict, List

from core.classify import days_label, simplified_sections
from core.models import Task

BG_COLOR = "#FFF9C4"  # 포스트잇 느낌 파스텔 옐로우
DEFAULT_SECTION_COLOR = "#455A64"
SECTION_COLORS = {
    "오늘 (일간)": "#EF6C00",
    "주간 (이번주~차주)": "#F9A825",
    "월간": "#1565C0",
}


def _section_color(label: str) -> str:
    return SECTION_COLORS.get(label, DEFAULT_SECTION_COLOR)


def show_checklist(groups: Dict[str, List[Task]], run_date: date,
                    on_save: Callable[[List[str]], None]) -> None:
    sections = simplified_sections(groups)

    root = tk.Tk()
    root.title(f"업무 체크리스트 - {run_date.isoformat()}")
    root.configure(bg=BG_COLOR)
    root.attributes("-topmost", True)
    root.geometry("560x640+80+80")

    title_font = tkfont.Font(family="맑은 고딕", size=13, weight="bold")
    section_font = tkfont.Font(family="맑은 고딕", size=11, weight="bold")
    item_font = tkfont.Font(family="맑은 고딕", size=10)
    meta_font = tkfont.Font(family="맑은 고딕", size=9)

    header = tk.Label(
        root, text=f"업무 체크리스트  ({run_date.strftime('%Y-%m-%d (%a)')})",
        font=title_font, bg=BG_COLOR, anchor="w", justify="left",
    )
    header.pack(fill="x", padx=12, pady=(12, 4))

    canvas = tk.Canvas(root, bg=BG_COLOR, highlightthickness=0)
    scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas, bg=BG_COLOR)

    scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=4)
    scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    check_vars: Dict[str, tk.BooleanVar] = {}

    if not sections:
        tk.Label(
            scroll_frame, text="오늘 특별히 챙길 업무가 없습니다.",
            font=section_font, bg=BG_COLOR, fg="#2E7D32",
        ).pack(anchor="w", pady=20)
    else:
        for label, tasks in sections:
            sec_label = tk.Label(
                scroll_frame, text=f"[ {label} ]  {len(tasks)}건",
                font=section_font, bg=BG_COLOR, fg=_section_color(label),
                anchor="w",
            )
            sec_label.pack(fill="x", pady=(12, 2))

            for t in tasks:
                var = tk.BooleanVar(value=False)
                check_vars[t.id] = var

                due_str = t.due_date.isoformat() if t.due_date else "?"
                d_label = days_label(t.due_date, run_date) if t.due_date else ""
                sender_str = t.sender or "발신자 미상"

                item_frame = tk.Frame(scroll_frame, bg=BG_COLOR)
                item_frame.pack(fill="x", padx=4, pady=(2, 6), anchor="w")

                # "누가 : 어떤일을 : 언제까지" 형태로 한눈에 보이도록 체크박스 문구를 구성한다.
                who_what_when = f"{sender_str}  :  {t.title}  :  {due_str}까지 ({d_label})"
                cb = tk.Checkbutton(
                    item_frame, text=who_what_when,
                    variable=var, font=item_font,
                    bg=BG_COLOR, anchor="w", justify="left", wraplength=460,
                    activebackground=BG_COLOR,
                )
                cb.pack(fill="x", anchor="w")

                meta_text = f"     [{t.source}/{t.folder}]"
                tk.Label(
                    item_frame, text=meta_text, font=meta_font, bg=BG_COLOR,
                    fg="#333333", anchor="w", justify="left", wraplength=460,
                ).pack(fill="x", anchor="w")

                if t.matched_text:
                    tk.Label(
                        item_frame, text=f'     원문: "{t.matched_text}"', font=meta_font,
                        bg=BG_COLOR, fg="#777777", anchor="w", justify="left", wraplength=460,
                    ).pack(fill="x", anchor="w")

    button_frame = tk.Frame(root, bg=BG_COLOR)
    button_frame.pack(fill="x", padx=12, pady=10)

    def _save_and_close():
        done_ids = [tid for tid, var in check_vars.items() if var.get()]
        on_save(done_ids)
        root.destroy()

    def _close_only():
        root.destroy()

    tk.Button(button_frame, text="완료 표시 저장하고 닫기", command=_save_and_close).pack(side="left")
    tk.Button(button_frame, text="그냥 닫기", command=_close_only).pack(side="right")

    root.mainloop()
