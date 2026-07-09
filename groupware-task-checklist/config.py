from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / ".state"
DEBUG_DIR = BASE_DIR / "debug_dumps"

load_dotenv(BASE_DIR / ".env")


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    try:
        return int(val) if val else default
    except ValueError:
        return default


def _get_list(name: str) -> List[str]:
    val = os.getenv(name, "")
    return [v.strip() for v in val.split(",") if v.strip()]


class Config:
    login_url: str = os.getenv("GW_LOGIN_URL", "")
    gw_id: str = os.getenv("GW_ID", "")
    gw_pw: str = os.getenv("GW_PW", "")

    mail_list_url: str = os.getenv("GW_MAIL_LIST_URL", "")
    approval_urls = {
        "부서함-완료함": os.getenv("GW_APPROVAL_DEPT_COMPLETED_URL", ""),
        "부서함-참조/회람함": os.getenv("GW_APPROVAL_DEPT_REFERENCE_URL", ""),
        "개인함-완료함": os.getenv("GW_APPROVAL_PERSONAL_COMPLETED_URL", ""),
        "개인함-참조/회람함": os.getenv("GW_APPROVAL_PERSONAL_REFERENCE_URL", ""),
    }

    mail_lookback_days: int = _get_int("MAIL_LOOKBACK_DAYS", 14)
    approval_lookback_days: int = _get_int("APPROVAL_LOOKBACK_DAYS", 14)

    # 목록이 최신순 정렬이라는 전제로, 조회기간보다 오래된 항목이 나올 때까지 다음 페이지로 넘어간다.
    # (하루 메일량이 많으면 첫 페이지(보통 50개)만으로는 조회기간을 다 못 채울 수 있어서 필요함)
    mail_max_pages: int = _get_int("MAIL_MAX_PAGES", 5)
    approval_max_pages: int = _get_int("APPROVAL_MAX_PAGES", 3)

    mail_subject_exclude: List[str] = _get_list("MAIL_SUBJECT_EXCLUDE") or ["전표승인요청서"]

    headed: bool = _get_bool("HEADED", False)
    slowmo_ms: int = _get_int("SLOWMO_MS", 0)

    login_id_selector: str = os.getenv("LOGIN_ID_SELECTOR", "")
    login_pw_selector: str = os.getenv("LOGIN_PW_SELECTOR", "")
    login_submit_selector: str = os.getenv("LOGIN_SUBMIT_SELECTOR", "")

    storage_state_path: Path = STATE_DIR / "storage_state.json"
    task_state_path: Path = STATE_DIR / "task_state.json"

    debug_dump: bool = _get_bool("DEBUG_DUMP", False)

    # ── 전자결재 결재 전 오류 검증 (임시함) ─────────────────────
    approval_temp_url: str = os.getenv("GW_APPROVAL_TEMP_URL", "")
    draft_form_filter: List[str] = _get_list("DRAFT_FORM_FILTER")  # 비우면 전체
    review_lookback_days: int = _get_int("REVIEW_LOOKBACK_DAYS", 14)
    review_max_drafts: int = _get_int("REVIEW_MAX_DRAFTS", 30)
    max_attachment_mb: int = _get_int("MAX_ATTACHMENT_MB", 15)
    max_attachment_pages: int = _get_int("MAX_ATTACHMENT_PAGES", 8)

    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    review_effort: str = os.getenv("REVIEW_EFFORT", "high")

    attachments_dir: Path = STATE_DIR / "attachments"
    reports_dir: Path = BASE_DIR / "reports"


config = Config()
