"""최초 1회(또는 세션 만료 시) 실행: 브라우저 창이 열리면 직접 로그인한 뒤,
터미널로 돌아와 Enter 를 누르면 로그인 세션(쿠키)을 .state/storage_state.json 에 저장한다.

이후 main.py 는 이 세션을 재사용하므로 매번 자동으로 ID/PW 입력할 필요가 없다.
캡차, 2차인증, 비밀번호 변경 안내 팝업 등 예상 못한 화면이 나와도 사람이 직접 처리하면 되므로
자동 로그인보다 훨씬 안정적이다.
"""

from __future__ import annotations

from playwright.sync_api import sync_playwright

from config import config


def main() -> None:
    if not config.login_url:
        print("GW_LOGIN_URL 이 .env 에 설정되어 있지 않습니다.")
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(config.login_url)

        print("\n브라우저 창에서 직접 로그인해주세요.")
        print("로그인이 완료되고 원하는 화면(받은메일함 등)이 보이면, 이 터미널로 돌아와 Enter 를 누르세요.")
        input("로그인 완료 후 Enter... ")

        config.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(config.storage_state_path))
        print(f"세션 저장 완료: {config.storage_state_path}")

        print("\n[선택] 이제 메일함/전자결재 완료함·참조함 화면으로 직접 이동해서")
        print("주소창의 URL을 복사해 .env 의 GW_MAIL_LIST_URL / GW_APPROVAL_*_URL 항목에 붙여넣으세요.")
        input("확인했으면 Enter를 눌러 브라우저를 닫습니다... ")

        browser.close()


if __name__ == "__main__":
    main()
