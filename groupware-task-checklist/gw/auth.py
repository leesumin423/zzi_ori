"""로그인 처리.

우선순위:
  1. 저장된 storage_state(쿠키) 재사용 -> login_setup.py 로 미리 만들어둔 세션.
  2. 세션이 만료됐으면, .env 에 GW_ID/GW_PW 가 있을 때 자동 로그인 시도(휴리스틱 선택자).
  3. 그것도 실패하면 LoginRequiredError 를 던져서 상위(main.py)가 사용자에게 안내하게 한다.

그룹웨어 로그인 폼의 정확한 선택자는 사이트마다 다르므로, 흔한 패턴을 순서대로 시도한다.
.env 의 LOGIN_ID_SELECTOR / LOGIN_PW_SELECTOR / LOGIN_SUBMIT_SELECTOR 를 채워두면
그 값을 최우선으로 사용한다.
"""

from __future__ import annotations

from .browser import GWSession

ID_SELECTOR_CANDIDATES = [
    "#userId", "#user_id", "#userid", "#id", "#loginId", "#login_id",
    "input[name='userId']", "input[name='user_id']", "input[name='id']",
    "input[name='loginId']", "input[placeholder*='아이디']", "input[type='text']",
]

PW_SELECTOR_CANDIDATES = [
    "#password", "#passwd", "#pw", "#userPw", "#loginPw",
    "input[name='password']", "input[name='passwd']", "input[name='pw']",
    "input[type='password']",
]

SUBMIT_SELECTOR_CANDIDATES = [
    "button[type='submit']", "input[type='submit']",
    "button:has-text('로그인')", "a:has-text('로그인')", "#loginBtn", ".login_btn",
]

LOGIN_ERROR_HINTS = ["아이디", "비밀번호", "일치하지", "로그인 실패", "잠금"]


class LoginRequiredError(RuntimeError):
    pass


def is_logged_in(session: GWSession, check_url: str) -> bool:
    page = session.page
    page.goto(check_url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    if "login" in page.url.lower():
        return False
    frame, pw_el = session.find_in_any_frame("input[type='password']")
    if pw_el is not None:
        return False
    return True


def _first_match(session: GWSession, candidates):
    for sel in candidates:
        if not sel:
            continue
        frame, el = session.find_in_any_frame(sel)
        if el is not None:
            return frame, el, sel
    return None, None, None


def auto_login(session: GWSession, login_url: str, gw_id: str, gw_pw: str,
                id_selector: str = "", pw_selector: str = "", submit_selector: str = "") -> bool:
    if not gw_id or not gw_pw:
        return False

    page = session.page
    page.goto(login_url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    id_candidates = ([id_selector] if id_selector else []) + ID_SELECTOR_CANDIDATES
    pw_candidates = ([pw_selector] if pw_selector else []) + PW_SELECTOR_CANDIDATES

    id_frame, id_el, _ = _first_match(session, id_candidates)
    pw_frame, pw_el, pw_sel = _first_match(session, pw_candidates)

    if id_el is None or pw_el is None:
        return False

    id_el.fill(gw_id)
    pw_el.fill(gw_pw)

    submit_candidates = ([submit_selector] if submit_selector else []) + SUBMIT_SELECTOR_CANDIDATES
    _, submit_el, _ = _first_match(session, submit_candidates)
    if submit_el is not None:
        submit_el.click()
    else:
        pw_el.press("Enter")

    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    if "login" in page.url.lower():
        return False
    _, pw_el_after = session.find_in_any_frame("input[type='password']")
    if pw_el_after is not None:
        return False
    return True


def ensure_logged_in(session: GWSession, login_url: str, check_url: str,
                      gw_id: str = "", gw_pw: str = "",
                      id_selector: str = "", pw_selector: str = "", submit_selector: str = "") -> None:
    if check_url and is_logged_in(session, check_url):
        return
    if auto_login(session, login_url, gw_id, gw_pw, id_selector, pw_selector, submit_selector):
        return
    raise LoginRequiredError(
        "그룹웨어 로그인 세션이 없거나 만료됐고, 자동 로그인도 실패했습니다. "
        "login_setup.py 를 다시 실행해서 수동으로 로그인 후 세션을 저장해주세요."
    )
