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
    actual_content: str = ''


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


def _find_matching_section(doc, keywords: list):
    for s in doc.sections:
        title = (s.title or '').strip()
        if not title:
            continue
        for kw in keywords:
            if kw and (kw in title or title in kw):
                return s
    return None


_ACTUAL_CONTENT_MAX_CHARS = 600


def _extract_actual_content(section) -> str:
    """체크리스트 항목과 매칭된 섹션에서 "실제 기재 내용"으로 보여줄 텍스트를
    뽑는다 — found/not-found 배지 대신, 지침서 요구사항과 나란히 놓고 담당자가
    직접 비교할 수 있게 하기 위함."""
    if section is None:
        return ''
    paragraphs = [p.strip() for p in section.paragraphs if p and p.strip()]
    text = '\n'.join(paragraphs)
    if len(text) > _ACTUAL_CONTENT_MAX_CHARS:
        text = text[:_ACTUAL_CONTENT_MAX_CHARS] + ' …(이하 생략, 본문에서 직접 확인)'
    table_count = len(section.tables)
    if table_count:
        note = f'[표 {table_count}개 포함 — 표 내용은 위 ②/본문에서 직접 확인]'
        text = f'{text}\n{note}' if text else note
    return text or '(본문 텍스트를 찾지 못했습니다 — 목차 제목 표현이 달라 매칭이 안 됐을 수 있습니다)'


def check_full_checklist(doc, checklist: list) -> tuple:
    """정기보고서_작성지침서(12개 장 44개 항목) 기반 참고 체크.

    "목차에 이 제목이 있다/없다"만으로는 실질적인 정보가 아니라는 피드백에 따라
    (DSD로 제출하면 목차 자체는 자동 생성됨), found/not-found 배지 대신 매칭된
    섹션의 "실제 기재 내용"을 지침서 필수 체크 문구와 나란히 보여준다 — 담당자가
    직접 대조해서 판단하는 용도. ①표에는 안 올리고(노이즈 방지) 별도 참고
    섹션으로만 노출한다.
    """
    report_type = detect_report_type(doc.doc_name)
    checklist_items = []
    for item in checklist:
        omitted = report_type in (item.get('omit_for') or [])
        matched_section = _find_matching_section(doc, item.get('keywords') or [])
        checklist_items.append(ChecklistItem(
            rule_id=item['id'], chapter=item['chapter'], chapter_title=item['chapter_title'],
            title=item['title'], must=item.get('must', ''), found=matched_section is not None,
            omitted=omitted, actual_content=_extract_actual_content(matched_section),
        ))
    return [], checklist_items


def run_all(doc) -> dict:
    report_type = detect_report_type(doc.doc_name)
    results = []
    # check_required_sections(순수 "목차 있다/없다")는 뺐다 — DSD로 제출하면
    # 목차 항목 자체는 자동으로 다 생기기 때문에 실질적인 정보가 아니라는
    # 피드백에 따른 것. check_full_checklist는 아래에서 별도로 호출해
    # "실제 기재 내용" 대조용 참고 목록(checklist_items)만 만들고, ①표
    # 노이즈(찾음/못찾음 pass/warn)는 더 이상 섞지 않는다.
    results += check_cover_fields(doc)

    checklist = load_checklist()
    _, checklist_items = check_full_checklist(doc, checklist)

    # AI 검수(Anthropic API) 없이도 규칙만으로 잡을 수 있는 자기모순 체크 —
    # 실제 반기보고서 검수 중 발견된 문제(증감표 산술 불일치, 분기 라벨 잔존)에서
    # 착안. arithmetic_checks.py 참고.
    from . import arithmetic_checks
    results += arithmetic_checks.check_increase_decrease_arithmetic(doc)
    results += arithmetic_checks.check_period_label_residue(doc, report_type)
    results += arithmetic_checks.check_subsidiary_change_consistency(doc)
    results += arithmetic_checks.check_history_five_years(doc)
    results += arithmetic_checks.check_share_totals_consistency(doc)

    return {
        'results': results,
        'checklist_items': checklist_items,
        'report_type': report_type,
    }
