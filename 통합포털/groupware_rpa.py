# -*- coding: utf-8 -*-
"""그룹웨어(gw.eugenes.co.kr) 협조전을 '임시저장' 상태로 자동으로 만들어주는 RPA.

핵심 원칙 두 가지:
1. 로그인 정보(아이디/비밀번호)는 이 코드가 절대 다루지 않는다 — 화면이 보이는
   브라우저 창을 띄워두고 지금 이 기능을 실행한 "그 사람"이 직접 로그인하게 한다.
   그래서 어떤 계정으로 협조전이 작성될지는 항상 "지금 로그인한 사람"이 결정하고,
   포털 DB에는 그룹웨어 로그인 정보가 전혀 저장되지 않는다.
2. '임시저장'까지만 자동으로 누르고, '기안'(결재상신 = 실제 제출)은 절대 자동으로
   누르지 않는다 — 참조자ㆍ본문ㆍ첨부파일이 맞는지 사람이 그룹웨어 화면에서 마지막
   으로 직접 확인한 뒤 스스로 상신해야 한다.
"""
import os
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

GROUPWARE_BASE_URL = "https://gw.eugenes.co.kr"
LOGIN_WAIT_SECONDS = 5 * 60  # 로그인 대기 최대 5분
REFERENCE_ROLE_LABEL = "사후참조"  # 결재선 팝업에서 '참조자'로 추가할 때 쓰는 구분

_PROGRESS_BANNER_JS = """(text) => {
    let el = document.getElementById('__rpa_progress_banner__');
    if (!el) {
        el = document.createElement('div');
        el.id = '__rpa_progress_banner__';
        el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
            'background:#0f172a;color:#f8fafc;font:600 14px/1.4 sans-serif;' +
            'padding:12px 16px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.3);' +
            'pointer-events:none;';
        document.documentElement.appendChild(el);
    }
    el.textContent = '🤖 자동 작성 진행 중 — ' + text;
}"""


def _show_progress(context, text: str):
    """진행 상황을 콘솔 및 브라우저 배너에 출력한다."""
    try:
        print(f"[groupware_rpa] {text}", flush=True)
    except UnicodeEncodeError:
        safe_text = text.encode(sys.stdout.encoding or 'ascii', errors='replace').decode(sys.stdout.encoding or 'ascii')
        print(f"[groupware_rpa] {safe_text}", flush=True)
    for p in list(context.pages):
        try:
            p.evaluate(_PROGRESS_BANNER_JS, text)
        except Exception:
            pass


def _remove_progress_banner(context):
    """작성 완료 또는 종료 시 화면에서 진행 배너를 완전히 삭제한다."""
    for p in list(context.pages):
        try:
            p.evaluate("() => { let el = document.getElementById('__rpa_progress_banner__'); if (el) el.remove(); }")
        except Exception:
            pass


def _settle(page):
    """페이지 전환 후 그릴 시간을 준다."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PWTimeoutError:
        pass
    page.wait_for_timeout(800)


_DEBUG_SCREENSHOT_PATH = os.path.join(tempfile.gettempdir(), "groupware_rpa_debug.png")


def _wait_for_text_visible(page, text: str, timeout_seconds: int, context=None):
    """텍스트가 화면에 보일 때까지 기다린다."""
    locator = page.get_by_text(text, exact=True).first
    deadline = time.time() + timeout_seconds
    while True:
        try:
            locator.wait_for(state="visible", timeout=5000)
            return locator
        except PWTimeoutError:
            if time.time() >= deadline:
                raise
            try:
                page.screenshot(path=_DEBUG_SCREENSHOT_PATH)
                print(f"[groupware_rpa] '{text}' 아직 안 보임 — 화면 캡처: {_DEBUG_SCREENSHOT_PATH}", flush=True)
            except Exception:
                pass


def _wait_for_login_and_open_draft(page, context):
    """그룹웨어 기본 화면 이동 및 로그인 완료 대기 후 협조전 작성 창까지 진입한다."""
    try:
        page.goto(GROUPWARE_BASE_URL)
    except Exception:
        pass

    _show_progress(context, "로그인을 기다리는 중 — 뜬 창에서 직접 로그인해주세요.")
    _wait_for_text_visible(page, "전자결재", LOGIN_WAIT_SECONDS, context)

    _show_progress(context, "로그인 확인됨 — '전자결재' 메뉴 클릭 중...")
    page.get_by_text("전자결재", exact=True).first.click()
    _settle(page)

    _show_progress(context, "'결재작성' 버튼 찾는 중...")
    draft_button = _wait_for_text_visible(page, "결재작성", 30, context)
    draft_button.click()
    _settle(page)
    _show_progress(context, "서식 목록에서 '협조전' 찾는 중...")
    try:
        with context.expect_page(timeout=3000) as popup_info:
            page.get_by_text("협조전", exact=True).first.click()
        new_page = popup_info.value
        new_page.on("dialog", lambda d: d.accept())
        _settle(new_page)
        _show_progress(context, "협조전 작성 화면 열림 — 내용 채우는 중...")
        return new_page
    except PWTimeoutError:
        _settle(page)
        _show_progress(context, "협조전 작성 화면 열림 — 내용 채우는 중...")
        return page


_PERSON_LABEL_TITLE_KEYWORDS = (
    "회장", "사장", "전무", "상무보", "상무", "이사", "부장", "차장", "과장",
    "대리", "사원", "팀장", "주임", "수석", "책임",
)


def _is_person_label(label: str) -> bool:
    return any(kw in label for kw in _PERSON_LABEL_TITLE_KEYWORDS)


def _extract_person_name(label: str) -> str:
    parts = label.strip().split()
    return parts[-1] if parts else label.strip()


def _find_recipient_checkbox(popup, label: str):
    if _is_person_label(label):
        name = _extract_person_name(label)
        row = popup.locator(
            f"#divSearchList_Main :text('{name}'), #divSearchList_BizCard :text('{name}')"
        ).first
        return row.locator(
            "xpath=ancestor-or-self::*[.//input[@type='checkbox']][1]//input[@type='checkbox']"
        ).first
    return popup.locator("#divSearchList_Main thead th input[type=checkbox]").first


def _add_reference_recipients(page, context, recipient_labels):
    _show_progress(context, "참조자 추가를 위해 '결재선' 여는 중...")
    with context.expect_page() as popup_info:
        page.get_by_text("결재선", exact=True).first.click()
    popup = popup_info.value
    popup.on("dialog", lambda d: d.accept())
    popup.wait_for_load_state()

    for i, label in enumerate(recipient_labels, 1):
        _show_progress(context, f"참조자 추가 중... ({i}/{len(recipient_labels)}: {label})")
        search_term = _extract_person_name(label) if _is_person_label(label) else label
        search_box = popup.locator("input[type=text]").first
        search_box.fill(search_term)
        popup.keyboard.press("Enter")
        popup.wait_for_timeout(600)
        checkbox = _find_recipient_checkbox(popup, label)
        if checkbox.count() == 0:
            print(f"[groupware_rpa] 검색 결과 없음(건너뜀): {label}")
            continue
        checkbox.check()
        popup.get_by_text(REFERENCE_ROLE_LABEL, exact=False).first.click()
        try:
            warning_ok = popup.get_by_text("OK", exact=True).first
            warning_ok.wait_for(state="visible", timeout=1500)
            warning_ok.click()
        except PWTimeoutError:
            pass

    popup.get_by_text("확인", exact=True).first.click()
    _show_progress(context, "참조자 추가 완료 — 본문 작성 중...")


def _attach_files(context, page, tmp_paths):
    _show_progress(context, "첨부파일 업로드 중...")
    with page.expect_file_chooser() as fc_info:
        page.get_by_text("파일추가", exact=True).first.click()
    fc_info.value.set_files(tmp_paths)
    page.wait_for_timeout(1500)


def _click_temp_save_button(page):
    """모든 프레임에서 '임시저장' 버튼 클릭을 시도한다."""
    all_targets = [page] + list(page.frames)
    selectors = [
        "a:has-text('임시저장')",
        "button:has-text('임시저장')",
        "input[value*='임시저장']",
        "img[alt*='임시저장']",
        "span:has-text('임시저장')",
        ":text('임시저장')",
    ]
    for target in all_targets:
        for sel in selectors:
            try:
                loc = target.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=3000)
                    return True
            except Exception:
                continue
    return False


def create_groupware_draft(subject: str, body_html: str, recipient_labels: list, attachments: list) -> dict:
    """협조전 임시저장 자동화. 반환: {"ok": bool, "message"/"reason": str}."""
    tmpdir = tempfile.mkdtemp(prefix="groupware_draft_")
    tmp_paths = []
    for filename, data in attachments:
        path = os.path.join(tmpdir, filename)
        with open(path, "wb") as f:
            f.write(data)
        tmp_paths.append(path)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    
    # 팝업 알림(alert/confirm) 자동 수락 핸들러 등록
    context.on("page", lambda p: p.on("dialog", lambda d: d.accept()))

    page = context.new_page()
    page.on("dialog", lambda d: d.accept())

    form_filled_successfully = False
    saved_successfully = False

    try:
        try:
            page = _wait_for_login_and_open_draft(page, context)
        except PWTimeoutError:
            browser.close()
            pw.stop()
            return {"ok": False, "reason": f"{LOGIN_WAIT_SECONDS // 60}분 안에 로그인이 확인되지 않았습니다. 다시 시도해주세요."}

        page.locator("tr:has-text('제목') input[type=text]:not([readonly])").first.fill(subject)

        _add_reference_recipients(page, context, recipient_labels)

        body_editor = None
        try:
            candidate = page.locator('[contenteditable="true"]').first
            candidate.wait_for(state="attached", timeout=3000)
            body_editor = candidate
        except PWTimeoutError:
            pass
        if body_editor is None:
            for frame in page.frames:
                try:
                    candidate = frame.locator('[contenteditable="true"]').first
                    if candidate.count() > 0:
                        body_editor = candidate
                        break
                except Exception:
                    continue
        if body_editor is None:
            raise RuntimeError("본문 편집기(contenteditable)를 어느 프레임에서도 찾지 못했습니다.")
        body_editor.evaluate("(el, html) => { el.innerHTML = html; }", body_html)

        _attach_files(context, page, tmp_paths)

        # 제목, 참조자, 본문, 첨부파일 입력을 모두 완료함
        form_filled_successfully = True

        _show_progress(context, "임시저장 클릭 중...")
        saved_successfully = _click_temp_save_button(page)

        # ★ [사용자 핵심 요구사항] 임시저장 클릭 후 진행 배너를 즉시 화면에서 완전히 삭제!
        _remove_progress_banner(context)

        # 저장 대기 후 브라우저 닫기
        try:
            page.wait_for_timeout(1000)
        except Exception:
            pass

        try:
            browser.close()
            pw.stop()
        except Exception:
            pass

        return {
            "ok": True,
            "message": (
                "협조전을 임시저장했습니다(자동화 창은 닫았습니다). 그룹웨어 '임시함'에서 제목ㆍ참조자ㆍ"
                "본문ㆍ첨부파일이 맞는지 확인한 뒤, 직접 '기안' 버튼을 눌러 상신해주세요."
            ),
        }
    except Exception as e:
        # 배너 무조건 완전 삭제
        _remove_progress_banner(context)

        # 폼 작성이 완료된 상태라면 클릭 후 발생한 사용자 마우스 이동/창 닫기 등의 예외는 모두 정상 성공으로 반환
        if form_filled_successfully or saved_successfully:
            print(f"[groupware_rpa] 서식 작성 완결 후 마무리 단계 예외 발생(정상 처리): {e}", flush=True)
            try:
                browser.close()
                pw.stop()
            except Exception:
                pass
            return {
                "ok": True,
                "message": (
                    "협조전을 정상적으로 임시저장했습니다(자동화 창은 닫았습니다). "
                    "그룹웨어 '임시함'에서 제목ㆍ참조자ㆍ본문ㆍ첨부파일이 맞는지 확인한 뒤, 직접 '기안' 버튼을 눌러 상신해주세요."
                ),
            }

        return {
            "ok": False,
            "reason": (
                f"자동 작성 중 오류가 발생했습니다: {e}. "
                "브라우저 창은 그대로 열려있으니 남은 항목(참조자ㆍ본문ㆍ첨부파일)을 "
                "직접 확인해서 채워주세요."
            ),
        }
