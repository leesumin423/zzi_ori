from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

from core.date_extract import extract_dates, guess_doc_date
from core.models import Task

from .browser import GWSession
from .scrape_common import open_row, scan_rows


def collect_approval_tasks(session: GWSession, folder_urls: Dict[str, str], run_date: date,
                            lookback_days: int, max_rows: int = 60,
                            open_detail: bool = True) -> List[Task]:
    """folder_urls: {"부서함-완료함": url, "부서함-참조/회람함": url, ...}
    (빈 문자열인 항목은 건너뜀 - .env 에서 아직 URL을 안 채운 경우)
    """
    page = session.page
    lookback_start = run_date - timedelta(days=lookback_days)
    tasks: List[Task] = []

    for folder_name, url in folder_urls.items():
        if not url:
            continue

        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        list_frame = session.largest_text_frame()
        row_texts = scan_rows(list_frame, max_rows=max_rows)

        for idx, row_text in enumerate(row_texts):
            doc_date = guess_doc_date(row_text, run_date)
            if doc_date < lookback_start:
                continue

            body_text = row_text
            if open_detail:
                try:
                    if open_row(list_frame, idx):
                        page.wait_for_timeout(600)
                        detail_frame = session.largest_text_frame()
                        body_text = detail_frame.locator("body").inner_text(timeout=5000)
                except Exception:
                    body_text = row_text

            combined = f"{row_text}\n{body_text}"
            matches = extract_dates(combined, doc_date)
            title = row_text.splitlines()[0][:120] if row_text else "(제목 없음)"

            for m in matches:
                tasks.append(
                    Task(
                        source="approval",
                        folder=folder_name,
                        title=title,
                        doc_date=doc_date,
                        due_date=m.due_date,
                        matched_text=m.matched_text,
                        url=page.url,
                    )
                )

    return tasks
