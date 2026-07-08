"""임시함(임시저장된 기안지)을 뒤져서 본문 텍스트와 첨부파일을 긁어온다.

실제 다운로드/본문 추출은 사이트 구조를 모르는 상태에서 만든 최선의 추정(휴리스틱)이다.
문제가 생기면 README의 "목록 인식 방식과 한계" 섹션을 참고해서 선택자를 조정하면 된다.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import List

from core.date_extract import guess_doc_date
from core.text_parse import parse_form_type, parse_sender, parse_subject

from gw.browser import GWSession
from gw.scrape_common import open_row, scan_rows

from .models import DraftDocument

_ATTACHMENT_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|hwp|zip|jpe?g|png)(\?|$)", re.I)


def _looks_like_attachment_link(href: str, text: str) -> bool:
    href = href or ""
    text = (text or "").strip()
    if _ATTACHMENT_EXT_RE.search(href) or _ATTACHMENT_EXT_RE.search(text):
        return True
    return any(kw in text for kw in ("다운로드", "첨부"))


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return name or "attachment"


def _download_attachments(session: GWSession, detail_frame, draft_id: str,
                           attachments_dir: Path, max_attachment_mb: int) -> List[Path]:
    saved: List[Path] = []
    try:
        links = detail_frame.locator("a")
        count = links.count()
    except Exception:
        return saved

    candidates = []
    for i in range(count):
        try:
            el = links.nth(i)
            href = el.get_attribute("href") or ""
            text = el.inner_text(timeout=500) or ""
        except Exception:
            continue
        if _looks_like_attachment_link(href, text):
            candidates.append(i)

    if not candidates:
        return saved

    dest_dir = attachments_dir / draft_id
    max_bytes = max_attachment_mb * 1024 * 1024

    for i in candidates:
        try:
            with session.page.expect_download(timeout=5000) as download_info:
                links.nth(i).click()
            download = download_info.value
            dest_dir.mkdir(parents=True, exist_ok=True)
            filename = _sanitize_filename(download.suggested_filename)
            dest_path = dest_dir / filename
            download.save_as(str(dest_path))
            if dest_path.stat().st_size > max_bytes:
                dest_path.unlink(missing_ok=True)
                continue
            saved.append(dest_path)
        except Exception:
            continue

    return saved


def collect_temp_drafts(session: GWSession, temp_url: str, run_date: date,
                         lookback_days: int, form_filter: List[str],
                         max_drafts: int, attachments_dir: Path,
                         max_attachment_mb: int, max_rows: int = 60,
                         download_attachments: bool = True) -> List[DraftDocument]:
    if not temp_url:
        return []

    page = session.page
    page.goto(temp_url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    list_frame = session.largest_text_frame()
    row_texts = scan_rows(list_frame, max_rows=max_rows)

    lookback_start = run_date - timedelta(days=lookback_days)
    drafts: List[DraftDocument] = []

    for idx, row_text in enumerate(row_texts):
        if len(drafts) >= max_drafts:
            break

        if form_filter and not any(kw in row_text for kw in form_filter):
            continue

        doc_date = guess_doc_date(row_text, run_date)
        if doc_date < lookback_start:
            continue

        body_text = row_text
        detail_frame = list_frame
        try:
            if open_row(list_frame, idx):
                page.wait_for_timeout(600)
                detail_frame = session.largest_text_frame()
                body_text = detail_frame.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = row_text

        title = parse_subject(body_text) or parse_subject(row_text)
        if not title:
            title = row_text.splitlines()[0][:120] if row_text else "(제목 없음)"
        form_type = parse_form_type(body_text) or parse_form_type(row_text) or ""
        drafter = parse_sender(body_text) or parse_sender(row_text) or ""

        attachment_paths: List[Path] = []
        if download_attachments:
            draft_id_seed = f"{idx}_{title}"[:80]
            attachment_paths = _download_attachments(
                session, detail_frame, draft_id_seed, attachments_dir, max_attachment_mb,
            )

        drafts.append(
            DraftDocument(
                title=title,
                form_type=form_type,
                drafter=drafter,
                body_text=body_text,
                url=page.url,
                attachment_paths=attachment_paths,
            )
        )

    return drafts
