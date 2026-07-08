"""전자결재 임시함 기안 문서를 결재 전에 AI로 검토한다.

흐름:
  1. 저장된 로그인 세션으로 그룹웨어 접속
  2. 임시함(GW_APPROVAL_TEMP_URL)에서 기안 문서 목록을 가져옴 (DRAFT_FORM_FILTER 로 필터 가능)
  3. 각 문서의 본문 + 첨부파일(PDF/DOCX/XLSX) 내용을 추출
  4. Claude API(claude-opus-4-8)로 오탈자/숫자오류/논증오류/누락을 검토
  5. 결과를 HTML 리포트로 저장하고 기본 브라우저로 열기

주의: 문서 본문과 첨부파일 내용이 Anthropic 서버로 전송됩니다.
회사 데이터 정책상 문제가 없는지 먼저 확인하세요.

실행: python review_drafts.py
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from config import config
from gw.auth import LoginRequiredError, ensure_logged_in
from gw.browser import GWSession
from review.attachments import extract_attachment
from review.drafts import collect_temp_drafts
from review.llm_review import review_drafts
from review.report import build_report_html, open_report, save_report

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "review.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("review_drafts")


def _notify_error(message: str) -> None:
    log.error(message)
    try:
        from tkinter import Tk, messagebox

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("기안 검토 - 오류", message)
        root.destroy()
    except Exception:
        pass


def main() -> None:
    run_date = date.today()
    log.info("=== 기안 검토 시작: %s ===", run_date.isoformat())

    if not config.approval_temp_url:
        _notify_error("GW_APPROVAL_TEMP_URL 이 .env 에 설정되어 있지 않습니다. 임시함 URL을 채워주세요.")
        return

    if not config.anthropic_api_key:
        _notify_error(
            "ANTHROPIC_API_KEY 가 .env 에 설정되어 있지 않습니다.\n"
            "https://console.anthropic.com 에서 API 키를 발급받아 .env 에 추가해주세요.\n"
            "(문서 내용이 Anthropic 서버로 전송되는 기능이니, 회사 데이터 정책을 먼저 확인하세요.)"
        )
        return

    session = GWSession(
        headed=config.headed, slowmo_ms=config.slowmo_ms, storage_state_path=config.storage_state_path,
    )
    try:
        ensure_logged_in(
            session, config.login_url, config.approval_temp_url,
            config.gw_id, config.gw_pw,
            config.login_id_selector, config.login_pw_selector, config.login_submit_selector,
        )
        session.save_storage_state(config.storage_state_path)

        log.info("임시함 조회 중...")
        drafts = collect_temp_drafts(
            session, config.approval_temp_url, run_date,
            config.review_lookback_days, config.draft_form_filter,
            config.review_max_drafts, config.attachments_dir, config.max_attachment_mb,
        )
    except LoginRequiredError as e:
        _notify_error(str(e))
        return
    except Exception:
        log.exception("임시함 조회 중 오류 발생")
        _notify_error("임시함 조회 중 오류가 발생했습니다. logs/review.log 를 확인해주세요.")
        return
    finally:
        session.close()

    log.info("검토 대상 기안 %d건 발견", len(drafts))

    for draft in drafts:
        for path in draft.attachment_paths:
            draft.attachments.append(extract_attachment(path, config.max_attachment_pages))

    if not drafts:
        log.info("검토할 기안 문서가 없습니다.")

    log.info("Claude API로 검토 중... (문서 수: %d)", len(drafts))
    reviews = review_drafts(drafts, config.anthropic_api_key, config.anthropic_model, config.review_effort)

    risky = sum(1 for r in reviews if not r.error and r.risk_level in ("위험", "주의"))
    log.info("검토 완료: 전체 %d건 중 지적사항 있는 문서 %d건", len(reviews), risky)

    html_content = build_report_html(reviews, run_date)
    report_path = save_report(html_content, config.reports_dir, run_date)
    log.info("리포트 저장: %s", report_path)
    open_report(report_path)

    log.info("=== 기안 검토 종료 ===")


if __name__ == "__main__":
    main()
