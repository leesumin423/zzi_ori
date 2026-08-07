"""한국어 맞춤법/문법 검사 모듈 — 교체 가능한 백엔드 구조.

무료 외부 맞춤법 검사 서비스(부산대 스피드검사기, 네이버 맞춤법검사기 우회)는
둘 다 비공식·비문서화 프로토콜이라 서비스 쪽 변경에 따라 언제든 깨질 수 있다.
그래서 이 패키지는 "여러 백엔드를 순서대로 시도" 구조로 만들었고, 전부
실패하면 예외 없이 빈 결과 + 에러 메시지를 돌려줘서 나머지 검토(변경내역/
작성기준)는 정상 진행되게 한다.

+ exclude_terms.json: 회사명·계열사명·전문용어처럼 맞춤법 검사기가 자주
오탐하는 단어를 걸러내는 허용목록. 실사용하면서 계속 채워나가는 파일이다.
과거 이 프로젝트를 접었던 이유가 "오탈자가 너무 많이(오탐이 너무 많이) 나와서"
였기 때문에, 이 필터가 실질적으로 제일 중요한 부분이다.
"""
import json
import os
import re
from dataclasses import dataclass, field

from .. import config


@dataclass
class Correction:
    original: str
    suggestion: str
    section_key: str = ''
    section_title: str = ''
    help: str = ''
    kind: str = 'other'  # 'spacing'(띄어쓰기만 다름) | 'other'(철자·표현 차이)
    locations: list = field(default_factory=list)  # [(section_key, section_title), ...] — 중복 통합용
    count: int = 1


class BackendUnavailable(Exception):
    """해당 백엔드에 연결할 수 없거나 응답 형식이 바뀌었을 때."""


@dataclass
class SpellCheckReport:
    corrections: list = field(default_factory=list)
    backend_used: str = ''
    errors: list = field(default_factory=list)  # 시도했다가 실패한 백엔드 메시지들


def load_exclude_terms() -> set:
    if os.path.exists(config.EXCLUDE_TERMS_PATH):
        with open(config.EXCLUDE_TERMS_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return set(data.get('terms', []))
    return set()


def add_exclude_term(term: str):
    terms = load_exclude_terms()
    terms.add(term)
    os.makedirs(os.path.dirname(config.EXCLUDE_TERMS_PATH), exist_ok=True)
    with open(config.EXCLUDE_TERMS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'terms': sorted(terms)}, f, ensure_ascii=False, indent=2)


_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?다요]\s)|\n')
_MAX_CHUNK_CHARS = 450  # 검사기들이 한 번에 받는 텍스트 길이 제한이 보통 500자 내외


def _chunk_text(text: str):
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p and p.strip()]
    chunk = ''
    for part in parts:
        if len(chunk) + len(part) + 1 > _MAX_CHUNK_CHARS and chunk:
            yield chunk
            chunk = part
        else:
            chunk = f"{chunk} {part}".strip() if chunk else part
    if chunk:
        yield chunk


def _get_backends():
    from . import pusan_backend, hanspell_backend
    # 사내망에서는 speller.cs.pusan.ac.kr 자체가 DNS로 안 잡혀 매번 실패하는 게
    # 확인돼서(일시적 장애가 아님), 검사할 때마다 실패 시도 + 안내문구가 반복
    # 노출되는 걸 피하려고 네이버를 1순위로 둔다. 부산대가 나중에 복구되면
    # 2순위 폴백으로 자동으로 다시 쓰인다.
    return [hanspell_backend.HanspellBackend(), pusan_backend.PusanBackend()]


def check_paragraphs(paragraphs, throttle_seconds: float = 0.3) -> SpellCheckReport:
    """paragraphs: [(section_key, section_title, text), ...]"""
    import time

    exclude_terms = load_exclude_terms()
    backends = _get_backends()
    report = SpellCheckReport()

    active_backend = None
    for backend in backends:
        try:
            backend.health_check()
            active_backend = backend
            break
        except BackendUnavailable as e:
            report.errors.append(f"{backend.name}: {e}")

    if active_backend is None:
        report.errors.append("사용 가능한 맞춤법 검사 백엔드가 없습니다 (네트워크 또는 서비스 장애로 보임).")
        return report

    report.backend_used = active_backend.name

    # 같은 표준 문구(예: 보일러플레이트 안내 문장)가 여러 섹션에 반복되면
    # 검사기도 매번 같은 지적을 반복한다. (original, suggestion) 기준으로
    # 중복을 하나로 묶고 등장 위치만 누적해서, 실제로 봐야 할 "종류" 수를 줄인다.
    grouped = {}

    for section_key, section_title, text in paragraphs:
        for chunk in _chunk_text(text):
            try:
                corrections = active_backend.check(chunk)
            except BackendUnavailable as e:
                report.errors.append(f"{active_backend.name} 처리 중 오류: {e}")
                continue
            for c in corrections:
                # 부분일치로 제외: 어미/조사가 붙은 형태("작성기준에")도 걸러내야 함
                if any(term in c.original for term in exclude_terms):
                    continue
                c.kind = 'spacing' if c.original.replace(' ', '') == c.suggestion.replace(' ', '') else 'other'
                dedup_key = (c.original, c.suggestion)
                if dedup_key in grouped:
                    existing = grouped[dedup_key]
                    existing.count += 1
                    if len(existing.locations) < 5:
                        existing.locations.append((section_key, section_title))
                else:
                    c.section_key, c.section_title = section_key, section_title
                    c.locations = [(section_key, section_title)]
                    grouped[dedup_key] = c
            if throttle_seconds:
                time.sleep(throttle_seconds)

    # 실제 철자/표현 차이(other)를 먼저, 단순 띄어쓰기 제안(spacing)은 뒤로
    report.corrections = sorted(grouped.values(), key=lambda c: (c.kind == 'spacing', -c.count))
    return report
