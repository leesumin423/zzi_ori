"""작성기준 준수 체크 — quarterly_report.yaml(표지·상위 목차, 분기보고서 시드)와
periodic_report_checklist.yaml(정기보고서_작성지침서 12개 장 44개 항목 전체)에
정의된 체크리스트를 파싱된 문서 구조와 대조한다.

structural(목차 항목 존재 여부) + 표지 필수 기재사항, 두 종류만 다룬다.
396페이지짜리 작성기준 전체를 규칙화한 게 아니라는 점을
README/화면에 항상 같이 안내한다.

periodic_report_checklist.yaml 쪽은 지침서 문서의 소제목을 그대로 키워드로 쓰기
때문에, 실제 DART 문서의 표현이 조금만 달라도 못 찾을 수 있다. 그래서 이 체크는
fail을 절대 내지 않고(warn까지만), 발견 여부와 무관하게 "필수 체크" 문구를 항상
결과 화면의 별도 참고 섹션에 노출해 최종 판단은 사람이 하도록 한다.
"""
import os
import re
from dataclasses import dataclass

import yaml

from .. import config


@dataclass
class RuleResult:
    rule_id: str
    description: str
    status: str  # 'pass' | 'fail' | 'warn'
    detail: str = ''


@dataclass
class ChecklistItem:
    """작성지침서 기반 필수 체크 참고 항목 — 결과 화면에 장별로 항상 노출된다."""
    rule_id: str
    chapter: int
    chapter_title: str
    title: str
    must: str
    found: bool
    omitted: bool = False


def load_ruleset(report_type_key: str = 'quarterly_report') -> dict:
    path = os.path.join(config.STANDARDS_DIR, f'{report_type_key}.yaml')
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def check_required_sections(doc, ruleset) -> list:
    results = []
    top_keys = {s.key for s in doc.sections if s.top_level}
    for item in ruleset.get('required_sections', []):
        ok = item['key'] in top_keys
        results.append(RuleResult(
            rule_id=item['key'],
            description=f"필수 목차: {item['title']}",
            status='pass' if ok else 'fail',
            detail=item.get('reason', '') if ok else f"{item.get('reason', '')} — 초안에서 이 항목을 찾지 못했습니다.".strip(' —'),
        ))

    alt = ruleset.get('financial_statement_alternatives', [])
    if alt:
        ok = any(key in top_keys for key in alt)
        results.append(RuleResult(
            rule_id='financial_statement',
            description="필수 목차: 재무제표(연결 또는 별도)",
            status='pass' if ok else 'fail',
            detail='연결재무제표/재무제표(별도) 둘 다 찾지 못했습니다.' if not ok else '',
        ))
    return results


def check_cover_fields(doc) -> list:
    results = []
    company_ok = bool((doc.company_name or '').strip())
    results.append(RuleResult(
        rule_id='company_name',
        description='표지: 회사명 기재 여부',
        status='pass' if company_ok else 'warn',
        detail='' if company_ok else '아직 비어 있습니다. 서식작성기 초안 단계면 정상일 수 있으나 제출 전엔 반드시 채워야 합니다.',
    ))

    cover = doc.section_by_key('COVER')
    period_text = ''
    if cover:
        for block in cover.blocks:
            if block.kind == 'table' and block.table:
                for row in block.table.rows:
                    joined = ' '.join(c.text for c in row.cells)
                    if '사업연도' in joined or '부터' in joined or '까지' in joined:
                        period_text += joined + ' '
    results.append(RuleResult(
        rule_id='fiscal_period',
        description='표지: 사업연도(부터~까지) 기재 여부',
        status='pass' if re.search(r'\d{4}년', period_text) else 'warn',
        detail='' if period_text else '표지에서 사업연도 기재를 찾지 못했습니다.',
    ))
    return results


def detect_report_type(doc_name: str) -> str:
    name = doc_name or ''
    if '분기보고서' in name:
        return '분기보고서'
    if '반기보고서' in name:
        return '반기보고서'
    return '사업보고서'


def _all_section_titles(doc) -> list:
    return [s.title for s in doc.sections if (s.title or '').strip()]


def load_checklist(checklist_key: str = 'periodic_report_checklist') -> list:
    path = os.path.join(config.STANDARDS_DIR, f'{checklist_key}.yaml')
    with open(path, encoding='utf-8') as f:
        return (yaml.safe_load(f) or {}).get('items', [])


def _keyword_found(titles: list, keywords: list) -> bool:
    for title in titles:
        for kw in keywords:
            if kw and (kw in title or title in kw):
                return True
    return False


def check_full_checklist(doc, checklist: list) -> tuple:
    """정기보고서_작성지침서(12개 장 44개 항목) 기반 확장 체크.

    제목 키워드가 초안 목차에 있는지만 보는 구조적 체크라 fail은 내지 않는다
    (found=False라도 warn까지만 — RuleResult 목록에 섞어 넣는다).
    두 번째 반환값은 결과 화면에서 항상 노출할 장별 '필수 체크' 참고 목록이다.
    """
    report_type = detect_report_type(doc.doc_name)
    titles = _all_section_titles(doc)

    rule_results = []
    checklist_items = []
    for item in checklist:
        omitted = report_type in (item.get('omit_for') or [])
        found = _keyword_found(titles, item.get('keywords') or [])
        checklist_items.append(ChecklistItem(
            rule_id=item['id'], chapter=item['chapter'], chapter_title=item['chapter_title'],
            title=item['title'], must=item.get('must', ''), found=found, omitted=omitted,
        ))
        if omitted:
            continue
        rule_results.append(RuleResult(
            rule_id=f"guide-{item['id']}",
            description=f"[{item['chapter']}장] {item['title']}",
            status='pass' if found else 'warn',
            detail='' if found else '초안 목차에서 이 소제목을 찾지 못했습니다 — 실제 누락인지, 표현 차이인지 직접 확인해주세요.',
        ))
    return rule_results, checklist_items


def run_all(doc) -> dict:
    report_type = detect_report_type(doc.doc_name)
    ruleset = load_ruleset('quarterly_report')
    results = []
    results += check_required_sections(doc, ruleset)
    results += check_cover_fields(doc)

    checklist = load_checklist()
    guide_results, checklist_items = check_full_checklist(doc, checklist)
    results += guide_results

    return {
        'results': results,
        'checklist_items': checklist_items,
        'report_type': report_type,
    }
