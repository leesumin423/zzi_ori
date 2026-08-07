"""DART(전자공시) Open API 클라이언트.

주가현황/server.py 의 DART 연동 패턴(키 로딩, document.xml zip 처리)을 그대로
따르되, 이 프로젝트는 원문 XML 구조(dart4.xsd) 자체가 필요하므로 document.xml은
디코딩된 "텍스트"가 아니라 파싱 가능한 bytes로 반환한다.
"""
import io
import json
import os
import zipfile

import requests

from . import config

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"
CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

_corp_code_map = None  # {종목코드: DART고유번호} — 최초 조회 시 지연 로딩


class DartApiError(Exception):
    pass


def has_api_key() -> bool:
    return bool(config.DART_API_KEY)


def fetch_disclosures(corp_code: str, bgn_de: str, end_de: str, pblntf_ty: str = None) -> list:
    """DART 공시 목록(list.json). pblntf_ty='A'면 정기공시만. 최신순으로 반환."""
    if not config.DART_API_KEY:
        raise DartApiError("DART_API_KEY가 설정되어 있지 않습니다 (.dart_api_key 파일 확인).")
    params = {
        "crtfc_key": config.DART_API_KEY, "corp_code": corp_code,
        "bgn_de": bgn_de, "end_de": end_de, "page_no": 1, "page_count": 100,
    }
    if pblntf_ty:
        params["pblntf_ty"] = pblntf_ty
    r = requests.get(LIST_URL, params=params, timeout=15)
    data = r.json()
    if data.get('status') != '000':
        if data.get('status') == '013':  # 조회된 데이터 없음(정상 케이스)
            return []
        raise DartApiError(f"DART 공시목록 조회 실패: {data.get('status')} {data.get('message')}")
    return data.get('list', [])


def fetch_document_xml(rcept_no: str) -> bytes:
    """DART 공시 원문(document.xml, zip으로 내려옴)의 첫 XML 엔트리를 raw bytes로 반환."""
    if not config.DART_API_KEY:
        raise DartApiError("DART_API_KEY가 설정되어 있지 않습니다 (.dart_api_key 파일 확인).")
    r = requests.get(DOCUMENT_URL, params={
        "crtfc_key": config.DART_API_KEY, "rcept_no": rcept_no,
    }, timeout=30)
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = z.namelist()
            if not names:
                raise DartApiError(f"문서({rcept_no}) 응답 zip이 비어있습니다.")
            return z.read(names[0])
    except zipfile.BadZipFile:
        # 키 오류 등은 zip이 아니라 JSON 에러가 내려온다.
        try:
            data = r.json()
            raise DartApiError(f"문서({rcept_no}) 조회 실패: {data.get('status')} {data.get('message')}")
        except ValueError:
            raise DartApiError(f"문서({rcept_no}) 응답을 zip으로 열 수 없습니다.")


def _load_corp_code_cache() -> dict:
    if os.path.exists(config.CORP_CODE_CACHE_PATH):
        with open(config.CORP_CODE_CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_corp_code_cache(mapping: dict):
    with open(config.CORP_CODE_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False)


def refresh_corp_code_bulk() -> dict:
    """DART corpCode.xml 전체 마스터를 내려받아 {종목코드: 고유번호} 캐시로 저장.
    상장사만 대상(종목코드 없는 비상장/코드미지정 법인은 제외)."""
    if not config.DART_API_KEY:
        raise DartApiError("DART_API_KEY가 설정되어 있지 않습니다 (.dart_api_key 파일 확인).")
    r = requests.get(CORP_CODE_URL, params={"crtfc_key": config.DART_API_KEY}, timeout=60)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0])
    import xml.etree.ElementTree as ET
    root = ET.fromstring(raw)
    mapping = {}
    for node in root.findall('list'):
        stock_code = (node.findtext('stock_code') or '').strip()
        corp_code = (node.findtext('corp_code') or '').strip()
        if stock_code:
            mapping[stock_code] = corp_code
    _save_corp_code_cache(mapping)
    return mapping


def get_corp_code(stock_code: str) -> str:
    """종목코드로 DART 고유번호 조회. 시드 목록 → 캐시 → (필요시 호출부에서
    refresh_corp_code_bulk 직접 호출) 순으로 찾는다."""
    global _corp_code_map
    stock_code = stock_code.strip()
    if stock_code in config.SEED_CORP_CODES:
        return config.SEED_CORP_CODES[stock_code]
    if _corp_code_map is None:
        _corp_code_map = _load_corp_code_cache()
    return _corp_code_map.get(stock_code, '')
