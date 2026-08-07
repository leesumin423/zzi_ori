import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
# .dart_api_key, .corp_code_cache.json은 통합포털의 다른 프로젝트들(예: 주가현황)과
# 같은 관례로 "앱 루트"에 둔다 — disclosure_review는 그 안의 한 기능일 뿐이라 루트는
# 통합포털 폴더 자체.
PORTAL_ROOT = os.path.dirname(PACKAGE_DIR)


# DART(전자공시) Open API 키 — 코드에 직접 적지 않고 환경변수나 .gitignore된
# 로컬 파일(.dart_api_key)에서만 읽는다. 둘 다 없으면 DART 조회 기능은 꺼진다.
# 키 발급: https://opendart.fss.or.kr
def _load_dart_api_key() -> str:
    key = os.getenv('DART_API_KEY', '').strip()
    if key:
        return key
    key_file = os.path.join(PORTAL_ROOT, '.dart_api_key')
    if os.path.exists(key_file):
        with open(key_file, encoding='utf-8') as f:
            return f.read().strip()
    return ''


DART_API_KEY = _load_dart_api_key()

CORP_CODE_CACHE_PATH = os.path.join(PORTAL_ROOT, '.corp_code_cache.json')


# 정기공시 AI 검수(ai_review.py)용 Anthropic API 키 — DART_API_KEY와 같은 관례로
# 환경변수 또는 .gitignore된 로컬 파일(.anthropic_api_key)에서만 읽는다. 둘 다
# 없으면 AI 검수 기능은 꺼지고(구조적 체크ㆍ전기대비 비교ㆍ맞춤법 검사는 그대로 동작),
# 화면에 키 설정 방법을 안내한다. 키 발급: https://console.anthropic.com
def _load_anthropic_api_key() -> str:
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if key:
        return key
    key_file = os.path.join(PORTAL_ROOT, '.anthropic_api_key')
    if os.path.exists(key_file):
        with open(key_file, encoding='utf-8') as f:
            return f.read().strip()
    return ''


ANTHROPIC_API_KEY = _load_anthropic_api_key()
GUIDE_DOCX_PATH = os.path.join(PORTAL_ROOT, 'static', 'guides', '정기공시_작성지침서.docx')

# 이 기능은 (주)동양 정기공시 정확도 검토 전용이라 다른 회사는 다루지 않는다.
SEED_CORP_CODES = {
    "001520": "00117337",  # (주)동양
}

EXCLUDE_TERMS_PATH = os.path.join(PACKAGE_DIR, 'spellcheck', 'exclude_terms.json')
STANDARDS_DIR = os.path.join(PACKAGE_DIR, 'standards')

# 재무제표/주석 성격의 표는 매 분기 숫자가 통째로 바뀌는 게 정상이라 값 단위
# 비교 대상에서 제외하고 구조(행 추가/삭제) 변화만 본다. 섹션 제목에 아래
# 키워드가 있으면 "재무제표류"로 분류.
FINANCIAL_STATEMENT_KEYWORDS = [
    '재무상태표', '손익계산서', '포괄손익계산서', '자본변동표', '현금흐름표',
    '재무제표 주석', '주석', '요약재무정보',
]
