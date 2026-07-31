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

화면(브라우저 창)에 지금 뭘 하고 있는지 배너로 계속 띄운다 — 이 자동화가 도는
동안 사람이 볼 수 있는 유일한 화면이 이 브라우저 창이라, 진행상황을 여기 직접
표시하지 않으면 "로그인했는데 아무 일도 안 일어난다"처럼 실제로는 동작 중인데도
멈춘 것처럼 보인다(실제로 겪은 문제).

주의: 아래 화면 요소(버튼 텍스트, 팝업 구조)는 사용자가 보내준 실제 화면
스크린샷을 보고 작성했지만, 이 코드 자체를 실제 그룹웨어에 대해 실행해본 적은
없다 — 그룹웨어 화면의 사소한 차이 때문에 일부 셀렉터 조정이 필요할 수 있다.
실패하면 브라우저 창에 표시된 배너가 "어느 단계에서" 멈췄는지 그대로 보여준다.
"""
import os
import tempfile
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# formID=206 URL이나 approval_Home.do 같은 세부 화면 URL을 직접 열면 안 된다 —
# 둘 다 실제로 시도해봤는데, 로그인 전 상태에서 이런 딥링크로 바로 들어가면
# 토큰이 없거나 SPA 라우팅이 초기화가 안 돼서 그냥 일반 포털 홈으로 튕겨버렸다
# (실제로 겪은 문제 — "결재작성" 버튼이 있어야 할 화면이 아니라 메일/최신게시
# 위젯이 있는 일반 홈 화면이 캡처됐다). 그래서 항상 기본 주소로 들어가서
# 로그인한 뒤, 사용자가 실제로 하는 것과 똑같이 상단 메뉴의 '전자결재'를
# 클릭해 들어가고, 그 안에서 '결재작성' → 서식 목록의 '협조전'까지 클릭한다.
GROUPWARE_BASE_URL = "https://gw.eugenes.co.kr"
LOGIN_WAIT_SECONDS = 5 * 60  # 로그인 대기 최대 5분
REFERENCE_ROLE_LABEL = "사후참조"  # 결재선 팝업에서 '참조자'로 추가할 때 쓰는 구분

_PROGRESS_BANNER_JS = """(text) => {
    let el = document.getElementById('__rpa_progress_banner__');
    if (!el) {
        el = document.createElement('div');
        el.id = '__rpa_progress_banner__';
        // pointer-events:none이 핵심이다 — 이게 없으면 이 배너가 화면 위쪽에
        // 깔려서, 바로 그 자리에 있는 실제 메뉴/버튼(전자결재, 결재선 등)의
        // 클릭을 가로채버린다(실제로 겪은 문제 — Playwright가 "element
        // intercepts pointer events"라고 알려줬다). 배너는 눈으로 보기만
        // 하고 클릭은 항상 아래 실제 화면으로 그대로 통과시켜야 한다.
        el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
            'background:#0f172a;color:#f8fafc;font:600 14px/1.4 sans-serif;' +
            'padding:10px 16px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.3);' +
            'pointer-events:none;';
        document.documentElement.appendChild(el);
    }
    el.textContent = '🤖 자동 작성 진행 중 — ' + text;
}"""


def _show_progress(context, text: str):
    """지금 뭘 하고 있는지 (1) 브라우저 창 배너와 (2) 이 서버를 띄운 콘솔 창
    양쪽에 다 출력한다 — 브라우저 배너 주입이 그 순간 실패해도(창이 아직 준비
    안 됐거나 CSP 등으로 막히는 경우) 콘솔에는 반드시 남아서, 진행 상황을
    확인할 방법이 최소 하나는 있게 한다(실제로 배너가 전혀 안 뜨는 문제를
    겪어서 콘솔 출력을 별도로 추가했다)."""
    print(f"[groupware_rpa] {text}", flush=True)
    for p in list(context.pages):
        try:
            p.evaluate(_PROGRESS_BANNER_JS, text)
        except Exception:
            pass


def _settle(page):
    """페이지 전환 후 그릴 시간을 준다. 'networkidle'을 기다리면 안 된다 —
    이런 사내 대시보드형 그룹웨어는 알림 갱신 등 백그라운드 요청이 끊임없이
    돌아서 네트워크가 절대 '한가해지지' 않기 때문에, networkidle을 기다리면
    매 단계마다 기본 타임아웃(30초)을 그대로 다 써버린다(실제로 겪은 문제 —
    "로그인은 됐는데 몇 분째 반응이 없다"의 진짜 원인이었다). 그 대신
    'domcontentloaded'만 기다리고 짧게 고정 대기한다."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except PWTimeoutError:
        pass
    page.wait_for_timeout(800)


_DEBUG_SCREENSHOT_PATH = os.path.join(tempfile.gettempdir(), "groupware_rpa_debug.png")


def _wait_for_text_visible(page, text: str, timeout_seconds: int, context=None):
    """텍스트가 화면에 보일 때까지 기다린다. 한 번에 길게 기다리는 대신 5초
    간격으로 반복하면서, 안 보일 때마다 지금 화면을 스크린샷으로 남긴다 —
    로그인 직후 공지사항 팝업 등에 가려서 안 넘어가는 경우를 직접 눈으로
    확인하기 위함(실제로 이 문제를 겪었다). 찾은 locator를 반환한다."""
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
    """그룹웨어 기본 화면으로 이동한 뒤, 로그인이 끝나야만 나타나는 상단 메뉴
    '전자결재'가 보일 때까지 기다려서 로그인 완료를 판단한다(URL 문자열로
    판단하는 방식은 SSO 리다이렉트 때문에 실패했다 — gw.eugenes.co.kr ↔
    sso.eugenes.co.kr을 오가서 주소만으로는 알 수 없었다). '전자결재'를
    클릭해 들어간 다음 '결재작성' → 서식 목록의 '협조전'까지 클릭한다.

    주의: approval_Home.do 같은 세부 화면 URL로 바로 들어가는 것도 시도했지만
    로그인 전 상태에서는 그냥 일반 포털 홈으로 튕겨버렸다(실제로 캡처해서
    확인함) — 그래서 항상 기본 주소 → 메뉴 클릭 순서로 간다."""
    try:
        page.goto(GROUPWARE_BASE_URL)
    except Exception:
        # SSO 리다이렉트 초반에 Playwright의 최초 이동 요청이
        # 'net::ERR_ABORTED'로 취소 처리되는 경우가 실제로 있었다 — 결국
        # 어딘가에 잘 도착해있을 가능성이 높으므로 여기서 끝내지 않고
        # 아래에서 실제 목적 화면 요소가 뜨는지로 다시 판단한다.
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
        _settle(new_page)
        _show_progress(context, "협조전 작성 화면 열림 — 내용 채우는 중...")
        return new_page
    except PWTimeoutError:
        _settle(page)
        _show_progress(context, "협조전 작성 화면 열림 — 내용 채우는 중...")
        return page


# 참조자 라벨에 이 중 하나라도 들어있으면 "부서 직급 이름" 형태의 개인으로 본다
# (예: "회전기사업/VPC(관리Part) 차장 김윤관") — 순수 팀명(예: "총무팀")과는 다른
# 방식으로 찾아야 한다(팀은 헤더의 "전체 선택" 체크박스, 개인은 그 사람 카드 자체의
# 체크박스).
_PERSON_LABEL_TITLE_KEYWORDS = (
    "회장", "사장", "전무", "상무보", "상무", "이사", "부장", "차장", "과장",
    "대리", "사원", "팀장", "주임", "수석", "책임",
)


def _is_person_label(label: str) -> bool:
    return any(kw in label for kw in _PERSON_LABEL_TITLE_KEYWORDS)


def _extract_person_name(label: str) -> str:
    """"회전기사업/VPC(관리Part) 차장 김윤관" -> "김윤관"(마지막 공백 토큰)."""
    parts = label.strip().split()
    return parts[-1] if parts else label.strip()


def _find_recipient_checkbox(popup, label: str):
    """참조자로 추가할 체크박스를 찾는다 — 팀명이면 검색 결과 헤더(팀 전체
    선택), 개인("부서 직급 이름")이면 그 사람 이름이 있는 카드 자체의
    체크박스. 왼쪽 조직도 트리(#groupTreeDiv)에도 같은 텍스트의 체크박스가
    있어서, 범위를 검색 결과 영역(#divSearchList_Main, #divSearchList_BizCard)
    으로 좁히지 않으면 트리 쪽(항상 맨 위 "동양" 전체)이 잘못 잡혔다(실제로
    겪은 문제 — 검사 도구로 확인해서 이 구조를 알아냈다)."""
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
    """상단 '결재선' 버튼 → 새 팝업 창에서 이름/부서를 검색해 '참조자'로 추가한다.
    결재자(결재목록)는 건드리지 않는다 — 이미 사용자 직급 기준으로 자동 설정돼
    있으므로 그대로 둔다."""
    _show_progress(context, "참조자 추가를 위해 '결재선' 여는 중...")
    with context.expect_page() as popup_info:
        page.get_by_text("결재선", exact=True).first.click()
    popup = popup_info.value
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
        # "이미 등록되어있습니다" 같은 경고 팝업이 뜰 수 있다(같은 부서를 두 번
        # 추가하려 하거나, 검색 결과가 이미 다른 이름으로 등록된 상급 조직과
        # 겹치는 경우 등 — 실제로 겪었다). 뜨면 확인을 눌러 닫고 다음 참조자로
        # 넘어간다 — 안 뜨면 짧게 기다리다 그냥 넘어간다.
        try:
            warning_ok = popup.get_by_text("OK", exact=True).first
            warning_ok.wait_for(state="visible", timeout=1500)
            warning_ok.click()
        except PWTimeoutError:
            pass

    popup.get_by_text("확인", exact=True).first.click()
    _show_progress(context, "참조자 추가 완료 — 본문 작성 중...")


def _attach_files(context, page, tmp_paths):
    """본문 편집기 아래 '첨부목록' 섹션의 '파일추가' 버튼으로 파일을 올린다."""
    _show_progress(context, "첨부파일 업로드 중...")
    with page.expect_file_chooser() as fc_info:
        page.get_by_text("파일추가", exact=True).first.click()
    fc_info.value.set_files(tmp_paths)
    page.wait_for_timeout(1500)  # 업로드 반영 대기


def create_groupware_draft(subject: str, body_html: str, recipient_labels: list, attachments: list) -> dict:
    """협조전 임시저장 자동화 — 자금계획ㆍ공정위 공시 등 어떤 협조전이든
    제목ㆍ본문ㆍ참조자 목록ㆍ첨부파일만 다르고 절차는 완전히 같아서 공용으로
    쓴다. attachments: [(filename, bytes), ...]. 반환: {"ok": bool, "message"/"reason": str}."""
    tmpdir = tempfile.mkdtemp(prefix="groupware_draft_")
    tmp_paths = []
    for filename, data in attachments:
        path = os.path.join(tmpdir, filename)
        with open(path, "wb") as f:
            f.write(data)
        tmp_paths.append(path)

    # sync_playwright()를 'with'로 쓰면 함수가 끝나는 순간 드라이버가 종료되면서
    # 열어둔 브라우저 창까지 같이 닫혀버린다 — 성공/실패와 무관하게 사람이 화면을
    # 계속 보고 확인해야 하므로, 여기서는 명시적으로 start()만 하고 끝까지 stop()을
    # 부르지 않는다(로그인 타임아웃처럼 확인할 화면 자체가 의미 없는 경우만 정리한다).
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    # 아래 전체(로그인 대기 포함)를 하나의 try로 감싼다 — 그룹웨어 자체의
    # 리다이렉트 경합처럼 예상 못한 예외가 로그인 단계에서 나면, 그걸 못 잡아서
    # Flask가 500 에러로 튕기고 사용자에게는 "누른 창만 뜨고 아무 반응 없음"
    # 으로 보였다(실제로 겪은 문제) — 이제는 어디서 나든 같은 방식으로
    # 처리한다.
    try:
        try:
            page = _wait_for_login_and_open_draft(page, context)
        except PWTimeoutError:
            browser.close()
            pw.stop()
            return {"ok": False, "reason": f"{LOGIN_WAIT_SECONDS // 60}분 안에 로그인이 확인되지 않았습니다. 다시 시도해주세요."}

        # "제목" 행 안에는 기안자 표시용 읽기전용(readonly) 입력칸도 같이 있어서
        # 그게 먼저 잡혔다(실제로 겪은 문제 — id="InitiatorDisplay") — 편집
        # 가능한(readonly가 아닌) 입력창만 골라야 한다.
        page.locator("tr:has-text('제목') input[type=text]:not([readonly])").first.fill(subject)

        _add_reference_recipients(page, context, recipient_labels)

        # 본문 편집기(리치 텍스트, contenteditable)에 HTML을 직접 넣는다.
        # 원래는 '디자인'/'HTML' 소스보기 탭을 클릭해서 넣으려 했는데, "HTML"
        # 탭 버튼의 위치를 못 찾는 문제가 있었다(실제로 겪음) — contenteditable
        # 요소의 innerHTML을 직접 설정하는 방식이 탭 버튼을 아예 안 눌러도
        # 되므로 더 안정적이다. 최상위 페이지에 없으면(리치 텍스트 편집기가
        # iframe 안에 있는 경우가 많다 — 실제로 겪음) 모든 프레임을 다 뒤진다.
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

        # 임시저장 — 여기서 멈춘다. '기안'(제출)은 절대 자동으로 누르지 않는다.
        # 저장이 되면 그룹웨어가 보통 '임시함' 목록으로 넘어간다 — 그 이동을
        # 기다려서(최대 8초) 실제로 저장이 반영됐는지 확인한다.
        _show_progress(context, "임시저장 클릭 중...")
        page.get_by_text("임시저장", exact=True).first.click()

        # 임시저장을 누르면 "완료되었습니다" 확인 다이얼로그가 먼저 뜨고, 그
        # OK를 눌러야 실제로 임시함(mode=TEMPSAVE) 화면으로 넘어간다.
        try:
            completion_ok = page.get_by_text("OK", exact=True).first
            completion_ok.wait_for(state="visible", timeout=5000)
            completion_ok.click()
        except PWTimeoutError:
            pass

        try:
            page.wait_for_url("**/*TempSave*", timeout=8000)
            _show_progress(context, "✅ 임시저장 완료 — 창을 닫습니다. 그룹웨어 임시함에서 확인 후 직접 '기안'을 눌러주세요.")
        except PWTimeoutError:
            page.wait_for_timeout(1500)
            _show_progress(context, "✅ 임시저장 버튼을 눌렀습니다 — 창을 닫습니다. 저장됐는지 그룹웨어에서 확인해주세요.")

        # 여기까지 왔으면 임시함에 안전하게 저장된 상태다 — 더 볼 필요 없으니
        # 자동화 창을 정리한다(실제 제출/기안은 여전히 사람이 그룹웨어에
        # 직접 로그인해서 스스로 눌러야 한다 — 이 창을 닫는 것과는 무관하다).
        browser.close()
        pw.stop()
        return {
            "ok": True,
            "message": (
                "협조전을 임시저장했습니다(자동화 창은 닫았습니다). 그룹웨어 '임시함'에서 제목ㆍ참조자ㆍ"
                "본문ㆍ첨부파일이 맞는지 확인한 뒤, 직접 '기안' 버튼을 눌러 상신해주세요."
            ),
        }
    except Exception as e:
        # 브라우저 창은 일부러 닫지 않는다 — 어디까지 채워졌는지 그대로 보고
        # 남은 항목을 사람이 직접 채울 수 있게 한다.
        _show_progress(context, f"❌ 오류로 멈췄습니다: {e}")
        return {
            "ok": False,
            "reason": (
                f"자동 작성 중 오류가 발생했습니다: {e}. "
                "브라우저 창은 그대로 열려있으니 남은 항목(참조자ㆍ본문ㆍ첨부파일)을 "
                "직접 확인해서 채워주세요."
            ),
        }
