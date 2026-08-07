"""초안(.dsd)과 기준 원문(전기 등 DART 제출본)을 섹션/표/문단 단위로 비교.

핵심 설계 포인트:
  - 섹션은 doc_parser가 뽑아준 AASSOCNOTE 기반 key로 정렬(조번호가 바뀌어도
    안정적).
  - 표의 행은 첫 칸(라벨) 텍스트로 정렬한다. 단, 재무제표 각주 번호
    "(주7,8)" 같은 꼬리표는 분기마다 바뀌므로 매칭 키에서는 제거하고 화면
    표시에는 원문 그대로 쓴다.
  - 재무제표류(재무상태표/손익계산서/현금흐름표/주석 등) 표는 숫자가 매
    분기 전부 바뀌는 게 정상이라 "값이 달라짐"은 보고하지 않고 행이
    추가/삭제됐는지(계정과목 구조 변화)만 본다. 그 외 표(임원현황,
    계열회사현황, 배당 등 서술형 표)는 값 변경까지 전부 보고한다.
"""
import difflib
import re
from dataclasses import dataclass, field
from itertools import zip_longest

from . import config
from . import doc_parser

# 분기ㆍ반기보고서는 작성기준상 일부 항목을 통째로 생략할 수 있고, 그런 경우
# 서식 자체가 "OO는 기업공시서식 작성기준에 따라 분기보고서에 기재하지
# 않습니다" 같은 문구를 넣어준다. 이런 정상적인 생략은 "차이"로 보고하면 안
# 되므로 diff_documents()에서 걸러낸다.
_OMISSION_TEXT_RE = re.compile(r'작성기준에\s*따라\s*(분기|반기)\s*보고서에\s*기재하지\s*않습니다')
# 위 문구 탐지로도 못 잡는 경우 — 항목(제목) 자체가 통째로 생성되지 않는 케이스
# (예: "II. 사업의 내용"의 세부 7개 항목은 분기ㆍ반기보고서에서 아예 하위 목차가
# 없다). 실제 관찰로 확인된 것만 우선 반영했고, 계속 검토하며 채워나가야 한다.
OMITTABLE_SECTION_KEYS = {
    'L-0-2-1-L1', 'L-0-2-2-L1', 'L-0-2-3-L1', 'L-0-2-4-L1',
    'L-0-2-5-L1', 'L-0-2-6-L1', 'L-0-2-7-L1',
}


def _is_omission_eligible_report(doc_name: str) -> bool:
    return ('분기보고서' in (doc_name or '')) or ('반기보고서' in (doc_name or ''))


# ── 단위(단위: 원/천원/백만원 등) 정합성 확인 ────────────────────────────
# 표 하나에 잘못된 단위를 써서 실제 금액이 1,000배ㆍ100만배 어긋나는 실수가
# 실무에서 종종 나온다는 피드백에 따른 체크. 같은 섹션이라도 표마다 단위가
# 다른 게 정상(예: 매출은 백만원, 생산량은 TON)이라 섹션별로 "등장하는 단위
# 집합"을 통째로 비교해서, 이전 기와 집합 자체가 달라졌을 때만 알려준다
# (표 단위로 정확히 어디가 문제인지 짚어주진 못하지만, 확인할 섹션을 좁혀준다).
_UNIT_RE = re.compile(r'단위\s*[:：]\s*([^)]+)')


def _extract_unit_sets(doc: doc_parser.ParsedDocument) -> dict:
    units_by_section = {}
    for s in doc.sections:
        found = set()
        for b in s.blocks:
            texts = []
            if b.kind == 'table' and b.table:
                for row in b.table.rows:
                    texts.extend(c.text for c in row.cells)
            elif b.text:
                texts.append(b.text)
            for t in texts:
                for m in _UNIT_RE.finditer(t):
                    found.add(re.sub(r'\s+', '', m.group(1)))
        if found:
            units_by_section[s.key] = found
    return units_by_section


@dataclass
class UnitMismatch:
    section_key: str
    section_title: str
    baseline_units: str
    draft_units: str


def check_unit_consistency(baseline: doc_parser.ParsedDocument, draft: doc_parser.ParsedDocument) -> list:
    base_units = _extract_unit_sets(baseline)
    draft_units = _extract_unit_sets(draft)
    draft_titles = {s.key: s.title for s in draft.sections}
    mismatches = []
    for key, d_set in draft_units.items():
        b_set = base_units.get(key)
        if b_set and b_set != d_set:
            mismatches.append(UnitMismatch(
                key, draft_titles.get(key, key),
                ', '.join(sorted(b_set)), ', '.join(sorted(d_set)),
            ))
    return mismatches


_FOOTNOTE_RE = re.compile(r'\s*\(주[\d,\s]+\)\s*$')
# "제69기" 같은 기수 표기나 "2025년 03월말" 같은 회차 라벨은 매년 자연스럽게
# 바뀌므로 행 매칭 키에서는 제거한다(같은 위치의 행끼리 정상적으로 짝지어지게).
# 표시용 텍스트(row.label 자체)는 그대로 두고, 매칭 키 계산에만 사용한다.
_FISCAL_TERM_RE = re.compile(r'제\s*\d+\s*기\s*(말)?')
_PERIOD_LABEL_RE = re.compile(r'\d{4}\s*년\s*\d{1,2}\s*월\s*(말)?')


def normalize_label(text: str) -> str:
    t = _FOOTNOTE_RE.sub('', text or '')
    t = _FISCAL_TERM_RE.sub('', t)
    t = _PERIOD_LABEL_RE.sub('', t)
    return t.strip()


def is_financial_statement_section(title: str) -> bool:
    return any(kw in (title or '') for kw in config.FINANCIAL_STATEMENT_KEYWORDS)


def _table_is_numeric_heavy(table) -> bool:
    """섹션 제목 키워드로 못 걸러낸 숫자 위주 표(예: 대손충당금설정률 같은
    재무비율표)를 값 셀 구성으로 추가 탐지. 라벨 열을 뺀 나머지 셀 중 다수가
    숫자/퍼센트/금액이면 매 분기 값이 바뀌는 게 정상인 표로 간주."""
    if len(table.rows) < 5:
        return False
    total = numeric = 0
    for row in table.rows:
        for cell in row.cells[1:]:
            if not cell.text:
                continue
            total += 1
            if cell.is_numeric_like:
                numeric += 1
    return total >= 5 and (numeric / total) >= 0.6


@dataclass
class SectionFlag:
    section_key: str
    section_title: str
    kind: str  # 'added' | 'removed' — draft 기준(added=초안에만 있음, removed=기준원문에만 있고 초안엔 없음)


@dataclass
class ParagraphChange:
    section_key: str
    section_title: str
    kind: str  # 'added' | 'removed' | 'changed'
    before: str = ''
    after: str = ''


@dataclass
class RowChange:
    section_key: str
    section_title: str
    table_index: int
    kind: str  # 'added' | 'removed'
    row_label: str


@dataclass
class CellChange:
    section_key: str
    section_title: str
    table_index: int
    row_label: str
    col_index: int
    before: str
    after: str


@dataclass
class UnifiedChange:
    """리뷰 화면에 "구분ㆍ전ㆍ후ㆍ차이내역ㆍ비고" 한 표로 보여주기 위한 통합
    행. section_flags/row_changes/cell_changes/paragraph_changes를 전부 이
    한 가지 모양으로 눌러 담는다 — 종류별로 표를 나눠놓으면 담당자가 한눈에
    "뭐가 달라졌는지" 파악하기 어렵다는 피드백에 따른 구성."""
    category: str    # 구분 (섹션/항목명)
    before: str      # 전(前) — 기준 원문 값. 신설된 항목이면 '없음'
    after: str       # 후(後) — 초안 값. 삭제된 항목이면 '없음'
    change_type: str  # 차이내역
    note: str = ''    # 비고


@dataclass
class DiffResult:
    section_flags: list = field(default_factory=list)
    paragraph_changes: list = field(default_factory=list)
    row_changes: list = field(default_factory=list)
    cell_changes: list = field(default_factory=list)
    table_count_mismatches: list = field(default_factory=list)
    omitted_count: int = 0  # 분기ㆍ반기보고서에서 정상적으로 생략 가능해 결과에서 뺀 건수

    def to_unified_rows(self) -> list:
        rows = []
        for f in self.section_flags:
            if f.kind == 'added':
                rows.append(UnifiedChange(f.section_title, '없음', '있음', '목차 항목 신설'))
            else:
                rows.append(UnifiedChange(f.section_title, '있음', '없음', '목차 항목 누락'))
        for r in self.row_changes:
            if r.kind == 'added':
                rows.append(UnifiedChange(r.section_title, '없음', r.row_label, '행 신설'))
            else:
                rows.append(UnifiedChange(r.section_title, r.row_label, '없음', '행 삭제'))
        for c in self.cell_changes:
            rows.append(UnifiedChange(c.section_title, c.before, c.after, f'"{c.row_label}" 값 변경'))
        paragraph_labels = {'added': '문단 신설', 'removed': '문단 삭제', 'changed': '문단 내용 변경'}
        for p in self.paragraph_changes:
            rows.append(UnifiedChange(
                p.section_title, p.before or '없음', p.after or '없음', paragraph_labels[p.kind]))
        rows.sort(key=lambda r: r.category)
        return rows


def _unique_row_index(rows):
    """행 라벨(각주 제거)을 키로 매핑. 같은 라벨이 여러 번 나오면 등장 순서로 구분."""
    seen = {}
    indexed = {}
    for row in rows:
        key = normalize_label(row.label)
        seen[key] = seen.get(key, 0) + 1
        indexed[(key, seen[key])] = row
    return indexed


def _diff_table(section_key, section_title, table_index, base_table, draft_table,
                 financial: bool, result: DiffResult):
    base_idx = _unique_row_index(base_table.rows)
    draft_idx = _unique_row_index(draft_table.rows)

    all_keys = list(dict.fromkeys(list(base_idx.keys()) + list(draft_idx.keys())))
    for key in all_keys:
        base_row = base_idx.get(key)
        draft_row = draft_idx.get(key)
        if base_row and not draft_row:
            result.row_changes.append(RowChange(
                section_key, section_title, table_index, 'removed', base_row.label))
        elif draft_row and not base_row:
            result.row_changes.append(RowChange(
                section_key, section_title, table_index, 'added', draft_row.label))
        elif not financial:
            n = max(len(base_row.cells), len(draft_row.cells))
            for col in range(1, n):
                b = base_row.cells[col].text if col < len(base_row.cells) else ''
                d = draft_row.cells[col].text if col < len(draft_row.cells) else ''
                if b != d:
                    result.cell_changes.append(CellChange(
                        section_key, section_title, table_index, draft_row.label, col, b, d))


def _diff_section_content(section_key, section_title, base_section, draft_section, result: DiffResult):
    sm = difflib.SequenceMatcher(None, base_section.paragraphs, draft_section.paragraphs)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        if tag == 'replace':
            for b, a in zip_longest(base_section.paragraphs[i1:i2], draft_section.paragraphs[j1:j2], fillvalue=''):
                result.paragraph_changes.append(ParagraphChange(
                    section_key, section_title, 'changed', before=b, after=a))
        elif tag == 'delete':
            for b in base_section.paragraphs[i1:i2]:
                result.paragraph_changes.append(ParagraphChange(
                    section_key, section_title, 'removed', before=b))
        elif tag == 'insert':
            for a in draft_section.paragraphs[j1:j2]:
                result.paragraph_changes.append(ParagraphChange(
                    section_key, section_title, 'added', after=a))

    section_is_financial = is_financial_statement_section(section_title)
    base_tables = base_section.tables
    draft_tables = draft_section.tables
    if len(base_tables) != len(draft_tables):
        result.table_count_mismatches.append(SectionFlag(section_key, section_title, 'table_count_mismatch'))
    for idx, (bt, dt) in enumerate(zip_longest(base_tables, draft_tables)):
        if bt is None or dt is None:
            continue
        financial = section_is_financial or _table_is_numeric_heavy(bt) or _table_is_numeric_heavy(dt)
        _diff_table(section_key, section_title, idx, bt, dt, financial, result)


def _is_stable_section_key(key: str) -> bool:
    """DART는 재무제표 주석의 개별 항목("1. 일반사항", "7. 유형자산" 등)까지도
    전부 ATOC="Y"(목차 항목)로 표시하지만, 이런 세부 항목은 AASSOCNOTE 같은
    안정적 코드가 없고 doc_parser가 ATOC-<번호> 형태로 임시 키를 붙인다.
    이런 세부 항목까지 전부 "추가/삭제"로 보고하면 재무제표 통째로 비어있는
    초안 하나 때문에 목차 변경 목록이 수십~수백 줄로 폭발한다. AASSOCNOTE
    기반의 "정식" 목차 키만 추가/삭제 대상으로 본다."""
    return not (key.startswith('ATOC-') or key.startswith('AUTO-'))


def diff_documents(baseline: doc_parser.ParsedDocument, draft: doc_parser.ParsedDocument) -> DiffResult:
    result = DiffResult()
    baseline_keys = {s.key: s for s in baseline.sections}
    draft_keys = {s.key: s for s in draft.sections}
    omission_eligible = _is_omission_eligible_report(draft.doc_name)

    for s in draft.sections:
        if s.top_level and s.key not in baseline_keys and _is_stable_section_key(s.key):
            result.section_flags.append(SectionFlag(s.key, s.title, 'added'))
    for s in baseline.sections:
        if s.top_level and s.key not in draft_keys and _is_stable_section_key(s.key):
            if omission_eligible and s.key in OMITTABLE_SECTION_KEYS:
                result.omitted_count += 1
                continue
            result.section_flags.append(SectionFlag(s.key, s.title, 'removed'))

    for s in draft.sections:
        base_section = baseline_keys.get(s.key)
        if base_section is None:
            continue
        _diff_section_content(s.key, s.title, base_section, s, result)

    if omission_eligible:
        kept = []
        for p in result.paragraph_changes:
            if p.kind in ('added', 'changed') and _OMISSION_TEXT_RE.search(p.after or ''):
                result.omitted_count += 1
                continue
            kept.append(p)
        result.paragraph_changes = kept

    return result
