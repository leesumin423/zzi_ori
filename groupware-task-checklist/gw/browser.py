from __future__ import annotations

from pathlib import Path
from typing import Optional

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
