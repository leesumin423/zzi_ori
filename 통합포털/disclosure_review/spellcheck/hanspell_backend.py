"""네이버 맞춤법 검사기 백엔드 (비공식 엔드포인트).

네이버 통합검색 결과 페이지(검색어: "맞춤법검사기")에 내장된 JS에서
`passportKey`를 매번 추출해 https://ts-proxy.naver.com/ocontent/util/SpellerProxy
를 호출한다. 이 키는 만료/회전될 수 있어 매 실행마다 새로 받아온다.

응답 JSON의 origin_html(원문 오류구간을 <span class='result_underline'>로 표시)과
html(교정 결과를 <em class='...'>로 표시)에서 같은 순서로 나오는 구간을
1:1로 짝지어 (원문 → 교정안) 쌍을 만든다.
"""
import re

import requests
from bs4 import BeautifulSoup

from . import BackendUnavailable, Correction

SEARCH_URL = "https://search.naver.com/search.naver"
CHECKER_BASE = "https://ts-proxy.naver.com/ocontent/util/SpellerProxy"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://search.naver.com/",
}
_KEY_RE = re.compile(r'checker:\s*"[^"]*passportKey=([a-f0-9]+)"')

_cached_key = None
_cached_key_time = 0.0
_KEY_TTL_SECONDS = 600


def _fetch_passport_key() -> str:
    import time
    global _cached_key, _cached_key_time
    if _cached_key and (time.time() - _cached_key_time) < _KEY_TTL_SECONDS:
        return _cached_key
    key = _fetch_passport_key_uncached()
    _cached_key, _cached_key_time = key, time.time()
    return key


def _fetch_passport_key_uncached() -> str:
    try:
        r = requests.get(SEARCH_URL, params={"query": "맞춤법검사기"}, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise BackendUnavailable(f"passportKey 조회용 페이지 접속 실패: {e}")
    m = _KEY_RE.search(r.text)
    if not m:
        raise BackendUnavailable("페이지에서 passportKey를 찾지 못했습니다 (네이버 쪽 구조 변경 가능성).")
    return m.group(1)


def _extract_spans(html_fragment: str, tag: str, class_prefix: str = None):
    soup = BeautifulSoup(html_fragment, 'html.parser')
    if class_prefix:
        return [el.get_text() for el in soup.find_all(tag, class_=re.compile(class_prefix))]
    return [el.get_text() for el in soup.find_all(tag)]


class HanspellBackend:
    name = "네이버 맞춤법 검사기"

    def health_check(self):
        _fetch_passport_key()

    def check(self, text: str):
        passport_key = _fetch_passport_key()
        try:
            r = requests.post(CHECKER_BASE, data={
                'passportKey': passport_key, 'q': text, 'color_blindness': 0,
            }, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            raise BackendUnavailable(f"요청 실패: {e}")
        except ValueError as e:
            raise BackendUnavailable(f"JSON 파싱 실패: {e}")

        try:
            result = data['message']['result']
        except (KeyError, TypeError):
            raise BackendUnavailable(f"응답 구조가 예상과 다릅니다: {data}")

        if not result.get('errata_count'):
            return []

        originals = _extract_spans(result.get('origin_html', ''), 'span')
        corrected = _extract_spans(result.get('html', ''), 'em')
        if len(originals) != len(corrected):
            raise BackendUnavailable(
                f"오류구간 개수 불일치(원문 {len(originals)} / 교정 {len(corrected)}) — 응답 형식이 바뀌었을 수 있습니다."
            )
        return [Correction(original=o.strip(), suggestion=c.strip())
                for o, c in zip(originals, corrected) if o.strip() != c.strip()]
