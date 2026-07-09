from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from core.date_extract import extract_dates, guess_doc_date
from core.models import Task
from core.text_parse import parse_sender, parse_subject

from .browser import GWSession
from .scrape_common import open_row, scan_rows

log = logging.getLogger(__name__)


def _dump(debug_dir: Optional[Path], folder_name: str, row_texts: List[str]) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = folder_name.replace("/", "_")
    path = debug_dir / f"approval_{safe_name}_{ts}.txt"
    lines = [f"=== 전자결재 [{folder_name}] 스캔 결과 ({len(row_texts)}개 행) ==="]
    for i, t in enumerate(row_texts):
        lines.append(f"\n--- 행 {i} ---\n{t}")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("전자결재[%s] 디버그 덤프 저장: %s", folder_name, path)


def collect_approval_tasks(session: GWSession, folder_urls: Dict[str, str], run_date: date,
                            lookback_days: int, max_rows: int = 60,
                            open_detail: bool = True,
                            debug_dir: Optional[Path] = None) -> List[Task]:
    """folder_urls: {"부서함-완료함": url, "부서함-참조/회람함": url, ...}
    (빈 문자열인 항목은 건너뜀 - .env 에서 아직 URL을 안 채운 경우)
    """
    page = session.page
    lookback_start = run_date - timedelta(days=lookback_days)
    tasks: List[Task] = []

    for folder_name, url in folder_urls.items():
        if not url:
            log.info("전자결재[%s]: URL 이 비어있어 건너뜀", folder_name)
            continue

        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        list_frame = session.largest_text_frame()
        row_texts = scan_rows(list_frame, max_rows=max_rows)
        log.info("전자결재[%s]: %d개 행 스캔됨", folder_name, len(row_texts))
        _dump(debug_dir, folder_name, row_texts)

        n_lookback_skipped = 0
        n_opened = 0
        n_matched = 0

        for idx, row_text in enumerate(row_texts):
            doc_date = guess_doc_date(row_text, run_date)
            if doc_date < lookback_start:
                n_lookback_skipped += 1
                continue

            body_text = row_text
            if open_detail:
                try:
                    if open_row(list_frame, idx):
                        page.wait_for_timeout(600)
                        detail_frame = session.largest_text_frame()
                        body_text = detail_frame.locator("body").inner_text(timeout=5000)
                        n_opened += 1
                except Exception:
                    body_text = row_text

            combined = f"{row_text}\n{body_text}"
            matches = extract_dates(combined, doc_date)
            if not matches:
                continue
            n_matched += 1

            title = parse_subject(body_text) or parse_subject(row_text)
            if not title:
                title = row_text.splitlines()[0][:120] if row_text else "(제목 없음)"
            sender = parse_sender(body_text) or parse_sender(row_text) or ""

            for m in matches:
                tasks.append(
                    Task(
                        source="approval",
                        folder=folder_name,
                        title=title,
                        sender=sender,
                        doc_date=doc_date,
                        due_date=m.due_date,
                        matched_text=m.matched_text,
                        url=page.url,
                    )
                )

        log.info(
            "전자결재[%s]: 기간초과 %d건, 상세열람 성공 %d건, 마감일 찾음 %d건",
            folder_name, n_lookback_skipped, n_opened, n_matched,
        )

    return tasks
