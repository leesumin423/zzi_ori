"""메모지(스티키 노트) 스타일의 업무 체크리스트 팝업.

tkinter 표준 라이브러리만 사용 (추가 설치 불필요, Windows 기본 python.org 설치본에는 기본 포함).
체크한 항목은 "완료 표시 저장하고 닫기" 버튼을 눌러야 저장된다 (core.state 로 넘김).
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import font as tkfont
from typing import Callable, Dict, List

from core.classify import BUCKET_LABELS, DEFAULT_VISIBLE_BUCKETS
from core.models import Task

BG_COLOR = "#FFF9C4"  # 포스트잇 느낌 파스텔 옐로우
SECTION_COLORS = {
    "OVERDUE": "#D32F2F",
    "TODAY": "#EF6C00",
    "THIS_WEEK": "#F9A825",
    "NEXT_WEEK": "#1565C0",
}


def show_checklist(groups: Dict[str, List[Task]], run_date: date,
                    on_save: Callable[[List[str]], None]) -> None:
    visible_buckets = [b for b in DEFAULT_VISIBLE_BUCKETS if groups.get(b)]

    root = tk.Tk()
    root.title(f"오늘의 업무 체크리스트 - {run_date.isoformat()}")
    root.configure(bg=BG_COLOR)
    root.attributes("-topmost", True)
    root.geometry("480x600+80+80")

    title_font = tkfont.Font(family="Malgun Gothic", size=13, weight="bold")
    section_font = tkfont.Font(family="Malgun Gothic", size=11, weight="bold")
    item_font = tkfont.Font(family="Malgun Gothic", size=10)

    header = tk.Label(
        root, text=f"📋 업무 체크리스트  ({run_date.strftime('%Y-%m-%d (%a)')})",
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

    if not visible_buckets:
        tk.Label(
            scroll_frame, text="🎉 오늘 특별히 챙길 업무가 없습니다.",
            font=section_font, bg=BG_COLOR, fg="#2E7D32",
        ).pack(anchor="w", pady=20)
    else:
        for bucket in visible_buckets:
            tasks = groups[bucket]
            sec_label = tk.Label(
                scroll_frame, text=f"{BUCKET_LABELS[bucket]}  ({len(tasks)}건)",
                font=section_font, bg=BG_COLOR, fg=SECTION_COLORS.get(bucket, "#333"),
                anchor="w",
            )
            sec_label.pack(fill="x", pady=(12, 2))

            for t in tasks:
                var = tk.BooleanVar(value=False)
                check_vars[t.id] = var
                due_str = t.due_date.isoformat() if t.due_date else "?"
                label_text = f"[{t.source}/{t.folder}] {t.title}\n   → 마감 {due_str}  ·  \"{t.matched_text}\""
                cb = tk.Checkbutton(
                    scroll_frame, text=label_text, variable=var, font=item_font,
                    bg=BG_COLOR, anchor="w", justify="left", wraplength=420,
                    activebackground=BG_COLOR,
                )
                cb.pack(fill="x", padx=4, pady=1, anchor="w")

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
