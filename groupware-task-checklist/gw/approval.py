from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from core.date_extract import extract_dates, guess_doc_date
from core.models import Task
from core.text_parse import parse_sender, parse_subject, strip_quoted_reply

from .browser import GWSession
from .scrape_common import go_to_next_page, is_excluded, open_row, scan_rows

log = logging.getLogger(__name__)


def _dump(debug_dir: Optional[Path], folder_name: str, row_texts: List[str]) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = folder_name.replace("/", "_")
    path = debug_dir / f"approval_{safe_name}_{ts}.txt"
    lines = [f"=== 전자결재 [{folder_name}] 스캔 결과 (총 {len(row_texts)}개 행, 여러 페이지 포함) ==="]
    for i, t in enumerate(row_texts):
        lines.append(f"\n--- 행 {i} ---\n{t}")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("전자결재[%s] 디버그 덤프 저장: %s", folder_name, path)


def collect_approval_tasks(session: GWSession, folder_urls: Dict[str, str], run_date: date,
                            lookback_days: int, max_rows: int = 60,
                            open_detail: bool = True,
                            debug_dir: Optional[Path] = None, max_pages: int = 3,
                            sender_exclude: Optional[List[str]] = None) -> List[Task]:
    """folder_urls: {"부서함-완료함": url, "부서함-참조/회람함": url, ...}
    (빈 문자열인 항목은 건너뜀 - .env 에서 아직 URL을 안 채운 경우)

    목록이 최신순으로 정렬돼 있다는 전제로, 조회기간(lookback_days)보다 오래된 행을 만나면
    그 페이지에서 멈추고 다음 페이지로 넘어가지 않는다. (자세한 설명은 gw/mail.py 참고)
    """
    page = session.page
    sender_exclude = sender_exclude or []
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

        all_row_texts: List[str] = []
        n_lookback_skipped = 0
        n_opened = 0
        n_matched = 0
        n_sender_excluded = 0

        for page_num in range(1, max_pages + 1):
            list_frame = session.largest_text_frame()
            row_texts = scan_rows(list_frame, max_rows=max_rows)
            log.info("전자결재[%s] %d페이지: %d개 행 스캔됨", folder_name, page_num, len(row_texts))
            if not row_texts:
                break
            all_row_texts.extend(row_texts)

            reached_lookback_end = False

            for idx, row_text in enumerate(row_texts):
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
                            body_text = strip_quoted_reply(text)
                            n_opened += 1
                    except Exception:
                        body_text = row_text

                sender = parse_sender(body_text) or parse_sender(row_text) or ""
                if sender and is_excluded(sender, sender_exclude):
                    n_sender_excluded += 1
                    continue

                combined = f"{row_text}\n{body_text}"
                matches = extract_dates(combined, doc_date)
                if not matches:
                    continue
                n_matched += 1

                title = parse_subject(body_text) or parse_subject(row_text)
                if not title:
                    title = row_text.splitlines()[0][:120] if row_text else "(제목 없음)"
                raw_snippet = body_text[:1500] if body_text else row_text[:1500]

                for m in matches:
                    tasks.append(
                        Task(
                            source="approval",
                            folder=folder_name,
                            title=title,
                            sender=sender,
                            doc_date=doc_date,
                            due_date=m.due_date,
                            matched_text=m.sentence,
                            raw_snippet=raw_snippet,
                            url=page.url,
                        )
                    )

            if reached_lookback_end:
                log.info("전자결재[%s]: %d페이지에서 조회기간 이전 항목을 만나 중단", folder_name, page_num)
                break
            if page_num >= max_pages:
                break
            if not go_to_next_page(list_frame, page_num + 1):
                break
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(500)

        _dump(debug_dir, folder_name, all_row_texts)
        log.info(
            "전자결재[%s]: 총 %d개 행, 기간초과 %d건, 상세열람 성공 %d건, 발신자 제외 %d건, 마감일 찾음 %d건",
            folder_name, len(all_row_texts), n_lookback_skipped, n_opened, n_sender_excluded, n_matched,
        )

    return tasks
