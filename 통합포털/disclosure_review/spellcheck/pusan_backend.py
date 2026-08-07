"""부산대학교 인공지능연구실 '한국어 맞춤법/문법 검사기'(스피드 검사기) 백엔드.

비공식·비문서화 엔드포인트(https://speller.cs.pusan.ac.kr)를 사용한다. 이
서비스는 커뮤니티에서도 종종 응답이 느리거나 일시적으로 막히는 것으로 알려져
있어, 응답 형식이 예상과 다르면 예외를 던지고 상위(spellcheck/__init__.py)가
다음 백엔드로 넘어가도록 한다.

이 샌드박스 환경에서는 해당 호스트의 DNS 해석 자체가 안 됐기 때문에(사내
네트워크 정책일 수도 있음) 실제 응답 형식은 사용자 PC에서 직접 실행하며
검증이 필요하다 — health_check() 실패 시 나오는 에러 메시지를 참고해서
_parse_response()를 조정하면 된다.
"""
import json
import re

import requests

from . import BackendUnavailable, Correction

BASE_URL = "https://speller.cs.pusan.ac.kr"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

_DATA_RE = re.compile(r"data\s*=\s*(\[.*?\])\s*;", re.DOTALL)


def _parse_response(html: str):
    match = _DATA_RE.search(html)
    if not match:
        raise BackendUnavailable(
            "응답에서 교정 결과(data = [...])를 찾지 못했습니다. "
            f"서비스 응답 형식이 바뀌었을 수 있습니다. (응답 일부: {html[:200]!r})"
        )
    raw = match.group(1)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BackendUnavailable(f"교정 결과 JSON 파싱 실패: {e}")

    corrections = []
    for item in items:
        orig = item.get('orgStr') or item.get('str') or ''
        cand = item.get('candWord') or ''
        if not orig:
            continue
        suggestion = cand.split('|')[0].strip() if cand else ''
        corrections.append(Correction(
            original=orig.strip(),
            suggestion=suggestion,
            help=item.get('help', '') or '',
        ))
    return corrections


class PusanBackend:
    name = "부산대 맞춤법/문법 검사기"

    def health_check(self):
        try:
            r = requests.get(BASE_URL, headers=HEADERS, timeout=6)
            if r.status_code >= 400:
                raise BackendUnavailable(f"연결 실패 (HTTP {r.status_code})")
        except requests.RequestException as e:
            raise BackendUnavailable(f"연결 실패: {e}")

    def check(self, text: str):
        try:
            r = requests.post(
                f"{BASE_URL}/results",
                data={"text1": text},
                headers=HEADERS,
                timeout=15,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise BackendUnavailable(f"요청 실패: {e}")
        return _parse_response(r.text)
