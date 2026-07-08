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

    mail_lookback_days: int = _get_int("MAIL_LOOKBACK_DAYS", 21)
    approval_lookback_days: int = _get_int("APPROVAL_LOOKBACK_DAYS", 21)

    mail_subject_exclude: List[str] = _get_list("MAIL_SUBJECT_EXCLUDE") or ["전표승인요청서"]

    headed: bool = _get_bool("HEADED", False)
    slowmo_ms: int = _get_int("SLOWMO_MS", 0)

    login_id_selector: str = os.getenv("LOGIN_ID_SELECTOR", "")
    login_pw_selector: str = os.getenv("LOGIN_PW_SELECTOR", "")
    login_submit_selector: str = os.getenv("LOGIN_SUBMIT_SELECTOR", "")

    storage_state_path: Path = STATE_DIR / "storage_state.json"
    task_state_path: Path = STATE_DIR / "task_state.json"

    debug_dump: bool = _get_bool("DEBUG_DUMP", False)


config = Config()
