from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Tuple

from playwright.sync_api import Frame, Page, sync_playwright


class GWSession:
    """Playwright 브라우저 세션 wrapper.

    storage_state_path가 존재하면 그 세션(쿠키)을 재사용해서 로그인을 건너뛴다.
    (login_setup.py 로 최초 1회 수동 로그인 후 저장된 파일)
    """

    def __init__(self, headed: bool = False, slowmo_ms: int = 0, storage_state_path: Optional[Path] = None):
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=not headed, slow_mo=slowmo_ms)
        storage_state = str(storage_state_path) if storage_state_path and storage_state_path.exists() else None
        self.context = self.browser.new_context(storage_state=storage_state)
        self.page: Page = self.context.new_page()

    @property
    def pw(self):
        return self._pw

    def save_storage_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.context.storage_state(path=str(path))

    def find_in_any_frame(self, selector: str):
        """지정 selector를 메인 프레임부터 모든 iframe까지 뒤져서 처음 찾은 (frame, element)를 반환."""
        for frame in self.page.frames:
            try:
                el = frame.query_selector(selector)
            except Exception:
                el = None
            if el:
                return frame, el
        return None, None

    def largest_text_frame(self) -> Frame:
        """가장 텍스트가 많은 frame을 '본문/상세 내용' frame으로 추정해서 반환."""
        best_frame = self.page.main_frame
        best_len = -1
        for frame in self.page.frames:
            try:
                text = frame.locator("body").inner_text(timeout=1000)
            except Exception:
                text = ""
            if len(text) > best_len:
                best_len = len(text)
                best_frame = frame
        return best_frame

    def open_detail(self, action: Callable[[], None], popup_wait_ms: int = 900,
                     content_timeout: int = 6000) -> Tuple[Optional[Page], Frame]:
        """action(예: 목록의 한 행 클릭)을 실행한 뒤, 상세 내용이 담긴 (팝업 또는 None, Frame)을 반환한다.

        그룹웨어 화면에 따라 두 가지 방식이 있다:
          1. 같은 창 안에서 iframe/내용이 바뀌는 방식 -> largest_text_frame() 으로 충분
          2. 클릭 시 새 브라우저 창(팝업, 예: "...WindowPop.aspx")이 뜨는 방식
             -> 새로 뜬 창을 감지해서 그 창 안의 frame을 읽어야 함
        새 창이 뜨는지 짧게(popup_wait_ms) 먼저 확인해보고, 안 뜨면 같은 창 방식으로 폴백한다.
        (매 행마다 긴 타임아웃을 다 기다리면 전체 실행이 너무 느려지므로 감지 자체는 짧게 한다.)

        팝업이 반환되면(popup is not None) **호출한 쪽에서 다 쓴 뒤 popup.close() 를 호출해야 한다.**
        """
        popup: Optional[Page] = None
        try:
            with self.context.expect_page(timeout=popup_wait_ms) as popup_info:
                action()
            popup = popup_info.value
        except Exception:
            popup = None

        if popup is not None:
            try:
                popup.wait_for_load_state("networkidle", timeout=content_timeout)
            except Exception:
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=content_timeout)
                except Exception:
                    pass
            best_frame = popup.main_frame
            best_len = -1
            for frame in popup.frames:
                try:
                    text = frame.locator("body").inner_text(timeout=1000)
                except Exception:
                    text = ""
                if len(text) > best_len:
                    best_len = len(text)
                    best_frame = frame
            return popup, best_frame

        # 새 창이 안 떴다 -> 같은 창 안에서 내용이 바뀌었다고 가정
        try:
            self.page.wait_for_timeout(400)
        except Exception:
            pass
        return None, self.largest_text_frame()

    def read_after_action(self, action: Callable[[], None], popup_wait_ms: int = 900,
                           content_timeout: int = 6000) -> str:
        """open_detail() 의 편의 버전 - 텍스트만 필요할 때 사용 (팝업이면 알아서 닫아준다)."""
        popup, frame = self.open_detail(action, popup_wait_ms, content_timeout)
        try:
            return frame.locator("body").inner_text(timeout=content_timeout)
        except Exception:
            return ""
        finally:
            if popup is not None:
                try:
                    popup.close()
                except Exception:
                    pass

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            self.browser.close()
            self._pw.stop()

    def __enter__(self) -> "GWSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
