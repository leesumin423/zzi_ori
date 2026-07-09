from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from core.date_extract import extract_dates, guess_doc_date
from core.models import Task
from core.text_parse import parse_receiver, parse_sender, parse_subject

from .browser import GWSession
from .scrape_common import is_excluded, open_row, scan_rows

log = logging.getLogger(__name__)


def _dump(debug_dir: Optional[Path], row_texts: List[str], opened_bodies: List[str]) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir / f"mail_scan_{ts}.txt"
    lines = [f"=== 메일함 스캔 결과 ({len(row_texts)}개 행) ==="]
    for i, t in enumerate(row_texts):
        lines.append(f"\n--- 행 {i} ---\n{t}")
    if opened_bodies:
        lines.append(f"\n\n=== 상세 열람된 본문 ({len(opened_bodies)}개) ===")
        for i, b in enumerate(opened_bodies):
            lines.append(f"\n--- 상세 {i} ---\n{b[:2000]}")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("메일함 디버그 덤프 저장: %s", path)


def collect_mail_tasks(session: GWSession, mail_list_url: str, run_date: date,
                        lookback_days: int, subject_exclude: List[str],
                        max_rows: int = 60, open_detail: bool = True,
                        debug_dir: Optional[Path] = None) -> List[Task]:
    if not mail_list_url:
        log.info("메일함: GW_MAIL_LIST_URL 이 비어있어 건너뜀")
        return []

    page = session.page
    page.goto(mail_list_url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    list_frame = session.largest_text_frame()
    row_texts = scan_rows(list_frame, max_rows=max_rows)
    log.info("메일함: %d개 행 스캔됨 (page url: %s)", len(row_texts), page.url)

    lookback_start = run_date - timedelta(days=lookback_days)
    tasks: List[Task] = []
    opened_bodies: List[str] = []

    n_excluded = 0
    n_lookback_skipped = 0
    n_opened = 0
    n_matched = 0

    for idx, row_text in enumerate(row_texts):
        if is_excluded(row_text, subject_exclude):
            n_excluded += 1
            continue

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
                    if debug_dir is not None:
                        opened_bodies.append(body_text)
                    if is_excluded(body_text[:200], subject_exclude):
                        continue
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
        receiver = parse_receiver(body_text) or parse_receiver(row_text) or ""

        for m in matches:
            tasks.append(
                Task(
                    source="mail",
                    folder="메일함",
                    title=title,
                    sender=sender,
                    receiver=receiver,
                    doc_date=doc_date,
                    due_date=m.due_date,
                    matched_text=m.matched_text,
                    url=page.url,
                )
            )

    log.info(
        "메일함: 제외(전표 등) %d건, 기간초과(%d일 이전) %d건, 상세열람 성공 %d건, 마감일 찾음 %d건 → 최종 %d건",
        n_excluded, lookback_days, n_lookback_skipped, n_opened, n_matched, len(tasks),
    )
    _dump(debug_dir, row_texts, opened_bodies)

    return tasks
