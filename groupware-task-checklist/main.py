"""그룹웨어 업무 체크리스트 - 메인 실행 스크립트.

흐름:
  1. 저장된 로그인 세션 재사용 (없거나 만료됐으면 자동 로그인 시도)
  2. 메일함 / 전자결재(부서함 완료함·참조함, 개인함 완료함·참조함) 를 뒤져서
     마감일이 언급된 항목을 모두 찾는다
  3. 실행일(오늘) 기준으로 지남/오늘/이번주/차주 로 분류
  4. 예전에 '완료' 체크한 항목은 제외
  5. 메모지 스타일 팝업으로 보여준다

실행: python main.py
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from config import DEBUG_DIR, config
from core.classify import classify_tasks, group_by_bucket
from core.state import apply_state, load_state, mark_done, save_state
from gw.approval import collect_approval_tasks
from gw.auth import LoginRequiredError, ensure_logged_in
from gw.browser import GWSession
from gw.mail import collect_mail_tasks

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("main")


def _notify_error(message: str) -> None:
    log.error(message)
    try:
        from tkinter import Tk, messagebox

        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("그룹웨어 업무 체크리스트 - 오류", message)
        root.destroy()
    except Exception:
        pass


def main() -> None:
    run_date = date.today()
    log.info("=== 실행 시작: %s ===", run_date.isoformat())

    check_url = config.mail_list_url or next((u for u in config.approval_urls.values() if u), "")
    if not check_url:
        _notify_error(
            "GW_MAIL_LIST_URL 또는 전자결재 URL이 .env 에 하나도 설정되어 있지 않습니다.\n"
            "login_setup.py 안내에 따라 .env 를 채워주세요."
        )
        return

    tasks = []
    session = GWSession(
        headed=config.headed, slowmo_ms=config.slowmo_ms, storage_state_path=config.storage_state_path
    )
    try:
        ensure_logged_in(
            session, config.login_url, check_url, config.gw_id, config.gw_pw,
            config.login_id_selector, config.login_pw_selector, config.login_submit_selector,
        )
        session.save_storage_state(config.storage_state_path)

        debug_dir = DEBUG_DIR if config.debug_dump else None

        log.info("메일함 조회 중...")
        tasks += collect_mail_tasks(
            session, config.mail_list_url, run_date,
            config.mail_lookback_days, config.mail_subject_exclude,
            debug_dir=debug_dir, max_pages=config.mail_max_pages,
        )
        log.info("전자결재함 조회 중...")
        tasks += collect_approval_tasks(
            session, config.approval_urls, run_date, config.approval_lookback_days,
            debug_dir=debug_dir, max_pages=config.approval_max_pages,
        )
    except LoginRequiredError as e:
        _notify_error(str(e))
        return
    except Exception:
        log.exception("크롤링 중 오류 발생")
        _notify_error(
            "그룹웨어 조회 중 오류가 발생했습니다. logs/run.log 를 확인해주세요.\n"
            "(사이트 구조가 예상과 달라 선택자를 조정해야 할 수 있습니다)"
        )
        return
    finally:
        session.close()

    log.info("마감일 언급 항목 %d건 발견", len(tasks))

    state = load_state(config.task_state_path)
    tasks = apply_state(tasks, state, run_date)
    tasks = classify_tasks(tasks, run_date)
    groups = group_by_bucket(tasks)
    save_state(state, config.task_state_path)

    def _on_save(done_ids):
        mark_done(done_ids, state, run_date)
        save_state(state, config.task_state_path)
        log.info("완료 처리: %d건", len(done_ids))

    from ui.popup import show_checklist

    show_checklist(groups, run_date, _on_save)
    log.info("=== 실행 종료 ===")


if __name__ == "__main__":
    main()
