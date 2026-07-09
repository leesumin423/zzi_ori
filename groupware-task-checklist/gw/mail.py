from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from core.date_extract import extract_dates, guess_doc_date
from core.models import Task
from core.text_parse import parse_receiver, parse_sender, parse_subject

from .browser import GWSession
from .scrape_common import go_to_next_page, is_excluded, open_row, row_html, scan_rows

log = logging.getLogger(__name__)


def _dump(debug_dir: Optional[Path], row_texts: List[str], opened_bodies: List[str],
          row_htmls: Optional[List[str]] = None) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir / f"mail_scan_{ts}.txt"
    lines = [f"=== 메일함 스캔 결과 (총 {len(row_texts)}개 행, 여러 페이지 포함) ==="]
    for i, t in enumerate(row_texts):
        lines.append(f"\n--- 행 {i} ---\n{t}")
    if opened_bodies:
        lines.append(f"\n\n=== 상세 열람된 본문 ({len(opened_bodies)}개) ===")
        for i, b in enumerate(opened_bodies):
            lines.append(f"\n--- 상세 {i} ---\n{b[:2000]}")
    if row_htmls:
        lines.append(
            f"\n\n=== 진단용: 행 원본 HTML ({len(row_htmls)}개, 클릭이 왜 안 먹히는지 확인용) ==="
        )
        for i, h in enumerate(row_htmls):
            lines.append(f"\n--- 행 HTML {i} ---\n{h[:3000]}")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("메일함 디버그 덤프 저장: %s", path)


def collect_mail_tasks(session: GWSession, mail_list_url: str, run_date: date,
                        lookback_days: int, subject_exclude: List[str],
                        max_rows: int = 60, open_detail: bool = True,
                        debug_dir: Optional[Path] = None, max_pages: int = 5) -> List[Task]:
    """메일함 목록을 조회기간(lookback_days)이 지난 항목이 나올 때까지 페이지를 넘겨가며 읽는다.

    목록이 "받은 날짜" 내림차순(최신순)으로 정렬돼 있다는 전제로, 한 페이지 안에서 조회기간보다
    오래된 행을 만나면 그 페이지에서 멈추고 다음 페이지로 넘어가지 않는다 (그래야 전체 페이지를
    다 훑지 않고도 필요한 만큼만 빠르게 읽을 수 있다). max_pages 는 혹시 정렬 가정이 틀렸을 때
    무한정 페이지를 넘기지 않도록 하는 안전장치다.
    """
    if not mail_list_url:
        log.info("메일함: GW_MAIL_LIST_URL 이 비어있어 건너뜀")
        return []

    page = session.page
    page.goto(mail_list_url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    lookback_start = run_date - timedelta(days=lookback_days)
    tasks: List[Task] = []
    all_row_texts: List[str] = []
    opened_bodies: List[str] = []
    row_htmls: List[str] = []

    n_excluded = 0
    n_lookback_skipped = 0
    n_opened = 0
    n_matched = 0

    for page_num in range(1, max_pages + 1):
        list_frame = session.largest_text_frame()
        row_texts = scan_rows(list_frame, max_rows=max_rows)
        log.info("메일함 %d페이지: %d개 행 스캔됨 (page url: %s)", page_num, len(row_texts), page.url)
        if not row_texts:
            break
        all_row_texts.extend(row_texts)

        if page_num == 1 and debug_dir is not None:
            for i in range(min(3, len(row_texts))):
                row_htmls.append(row_html(list_frame, i))

        reached_lookback_end = False

        for idx, row_text in enumerate(row_texts):
            if is_excluded(row_text, subject_exclude):
                n_excluded += 1
                continue

            doc_date = guess_doc_date(row_text, run_date)
            if doc_date < lookback_start:
                n_lookback_skipped += len(row_texts) - idx
                reached_lookback_end = True
                break

            body_text = row_text
            if open_detail:
                clicked = {"ok": False}

                def _click(idx=idx):
                    clicked["ok"] = open_row(list_frame, idx)

                try:
                    text = session.read_after_action(_click)
                    if clicked["ok"] and text:
                        body_text = text
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

        if reached_lookback_end:
            log.info("메일함: %d페이지에서 조회기간(%d일) 이전 항목을 만나 중단", page_num, lookback_days)
            break

        if page_num >= max_pages:
            log.info("메일함: 최대 페이지 수(%d)에 도달해 중단", max_pages)
            break

        if not go_to_next_page(list_frame, page_num + 1):
            log.info("메일함: 다음 페이지 버튼을 못 찾음 (마지막 페이지로 추정)")
            break
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(500)

    log.info(
        "메일함: 총 %d개 행(전 페이지 합산), 제외(전표 등) %d건, 기간초과(%d일 이전) %d건, "
        "상세열람 성공 %d건, 마감일 찾음 %d건 → 최종 %d건",
        len(all_row_texts), n_excluded, lookback_days, n_lookback_skipped, n_opened, n_matched, len(tasks),
    )
    _dump(debug_dir, all_row_texts, opened_bodies, row_htmls)

    return tasks
