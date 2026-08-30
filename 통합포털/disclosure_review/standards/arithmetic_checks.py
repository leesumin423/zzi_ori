"""AI 없이 규칙만으로 잡을 수 있는 "자기모순" 오류 체크.

standards/rules.py의 체크(목차 제목 존재 여부)나 diff_engine(전기 대비 변경)과
달리, 이 모듈은 문서 하나 안에서 숫자끼리 앞뒤가 안 맞는지, 이번 회차에 안 맞는
시점 표현(분기/반기)이 남아있는지를 본다. 실제 사용자 피드백(반기보고서 검수
중 발견) 기반:
  - 비상장회사 개요의 지분 증감표에서 "증가"에 숫자가 들어있는데 실제로는
    증가가 없었던 경우 → 기초+증가-감소=기말 산술 불일치로 잡힘
  - 자기주식 소각현황에 오기(誤記)로 보이는 거대한 숫자 → 같은 산술 체크로 잡힘
    (오기면 대개 기초+증가-감소=기말 등식이 깨진다)
  - 표에 "26년 1분기"처럼 분기 라벨이 반기보고서에 남아있는 경우

내용을 "이해"해야 판단되는 것(다른 근거자료와 대조해야 아는 것, 문장이
자연스러운지 등)은 여기서 다루지 않는다 — 그건 AI 검수(ai_review.py)의 몫이다.
"""
import re
from dataclasses import dataclass

from .rules import RuleResult


_BEGIN_KEYWORDS = ('기초',)
_INCREASE_KEYWORDS = ('증가',)
_DECREASE_KEYWORDS = ('감소',)
_END_KEYWORDS = ('기말',)

# 괄호로 감싼 음수 표기, 천단위 콤마, 퍼센트 기호까지 처리
_NUM_RE = re.compile(r'^\(?-?[\d,]+(\.\d+)?\)?%?$')


def _parse_number(text: str):
    t = (text or '').strip()
    if t in ('', '-', '−', 'N/A', '해당없음', '해당 없음'):
        return 0.0 if t in ('-', '−') else None
    neg = t.startswith('(') and t.endswith(')')
    core = t[1:-1] if neg else t
    core = core.replace(',', '').replace('%', '').strip()
    if not _NUM_RE.match(t) and not re.fullmatch(r'-?\d+(\.\d+)?', core):
        return None
    try:
        v = float(core)
    except ValueError:
        return None
    return -v if neg else v


def _header_rows(table):
    th_rows = [r for r in table.rows if r.cells and all(c.tag == 'TH' for c in r.cells)]
    return th_rows if th_rows else table.rows[:1]


def _header_texts(table):
    rows = _header_rows(table)
    if len(rows) == 1:
        return [c.text for c in rows[0].cells]
    width = max(len(r.cells) for r in rows)
    combined = []
    for i in range(width):
        parts = [r.cells[i].text for r in rows if i < len(r.cells) and r.cells[i].text]
        combined.append(' '.join(parts))
    return combined


def _find_col(headers, keywords):
    for i, h in enumerate(headers):
        if any(kw in h for kw in keywords):
            return i
    return None


@dataclass
class _Cols:
    begin: int
    increase: int
    decrease: int
    end: int


def check_increase_decrease_arithmetic(doc) -> list:
    """"기초/증가/감소/기말" 컬럼이 있는 표(지분 증감, 자기주식 취득·소각,
    전환사채 등 DART에서 흔한 패턴)에서 기초+증가-감소=기말이 맞는지 확인한다.
    """
    results = []
    for s in doc.sections:
        for t_idx, table in enumerate(s.tables):
            if len(table.rows) < 2:
                continue
            headers = _header_texts(table)
            begin_col = _find_col(headers, _BEGIN_KEYWORDS)
            end_col = _find_col(headers, _END_KEYWORDS)
            if begin_col is None or end_col is None:
                continue
            inc_col = _find_col(headers, _INCREASE_KEYWORDS)
            dec_col = _find_col(headers, _DECREASE_KEYWORDS)
            if inc_col is None and dec_col is None:
                continue

            header_row_count = len(_header_rows(table))
            data_rows = table.rows[header_row_count:]
            for row in data_rows:
                cells = row.cells
                needed = [c for c in (begin_col, inc_col, dec_col, end_col) if c is not None]
                if not needed or len(cells) <= max(needed):
                    continue
                begin = _parse_number(cells[begin_col].text)
                end = _parse_number(cells[end_col].text)
                if begin is None or end is None:
                    continue
                inc = _parse_number(cells[inc_col].text) if inc_col is not None else 0.0
                dec = _parse_number(cells[dec_col].text) if dec_col is not None else 0.0
                inc = inc if inc is not None else 0.0
                dec = dec if dec is not None else 0.0
                if inc == 0.0 and dec == 0.0 and begin == end:
                    continue  # 변동 없음 — 정상
                expected = begin + inc - dec
                tolerance = max(1.0, abs(end) * 0.001)
                if abs(expected - end) > tolerance:
                    results.append(RuleResult(
                        rule_id=f'arith-{s.key}-{t_idx}-{row.label}',
                        description=f'[{s.title}] "{row.label}" 행 산술 불일치',
                        status='warn',
                        detail=(
                            f'기초({begin:,.0f}) + 증가({inc:,.0f}) − 감소({dec:,.0f}) '
                            f'= {expected:,.0f} 인데, 표에 기재된 기말은 {end:,.0f}입니다 — '
                            '오기이거나 기초/증가/감소 중 하나가 빠졌을 수 있습니다. 직접 확인해주세요.'
                        ),
                    ))
    return results


# 회차 표시(1분기/2분기/3분기/4분기) 잔존 체크. "반기"라는 단어 자체는 사업보고서/
# 분기보고서에도 정상적으로 등장할 수 있어(예: "상반기 실적") 반대 방향(분기보고서에
# "반기" 잔존)은 오탐이 많을 것 같아 다루지 않는다 — 분기 → 반기/사업보고서 방향만.
_QUARTER_LABEL_RE = re.compile(r'[1-4]\s*분기')


def check_period_label_residue(doc, report_type: str) -> list:
    """반기보고서/사업보고서인데 표·본문에 "OO분기" 라벨이 남아있으면 경고.
    이전 회차(분기보고서) 서식을 그대로 복사해서 만들 때 라벨을 안 고친 경우를
    잡기 위한 체크 — 실제로 이렇게 놓친 사례가 보고됐다."""
    if report_type not in ('반기보고서', '사업보고서'):
        return []
    results = []
    for s in doc.sections:
        found_in_section = set()
        for b in s.blocks:
            texts = []
            if b.kind == 'table' and b.table:
                for row in b.table.rows:
                    texts.extend(c.text for c in row.cells if c.text)
            elif b.text:
                texts.append(b.text)
            for t in texts:
                for m in _QUARTER_LABEL_RE.finditer(t):
                    found_in_section.add(m.group(0).replace(' ', ''))
        if found_in_section:
            labels = ', '.join(sorted(found_in_section))
            results.append(RuleResult(
                rule_id=f'period-residue-{s.key}',
                description=f'[{s.title}] "{report_type}"인데 분기 라벨({labels}) 발견',
                status='warn',
                detail='이전 분기보고서 서식을 복사한 뒤 라벨을 안 고쳤을 가능성이 있습니다 — 실제 오기인지 확인해주세요.',
            ))
    return results


def check_subsidiary_change_consistency(doc) -> list:
    """"1. 연결대상 종속회사 개황" 표의 증가/감소 숫자와, "1-1 연결대상의
    변동내용"에 실제로 나열된 신규연결/연결제외 회사 수가 맞는지 대조한다.
    둘 다 같은 문서 안에 있는 숫자라 AI 없이 규칙으로 비교 가능하다."""
    results = []
    overview_sections = [
        s for s in doc.sections
        if '종속회사' in (s.title or '') and ('개황' in (s.title or '') or '현황' in (s.title or ''))
    ]
    if not overview_sections:
        return results

    increase = decrease = None
    for s in overview_sections:
        for table in s.tables:
            headers = _header_texts(table)
            inc_col = _find_col(headers, _INCREASE_KEYWORDS)
            dec_col = _find_col(headers, _DECREASE_KEYWORDS)
            if inc_col is None and dec_col is None:
                continue
            header_row_count = len(_header_rows(table))
            for row in table.rows[header_row_count:]:
                if row.label.strip() in ('합계', '계', '총계'):
                    if inc_col is not None and inc_col < len(row.cells):
                        increase = _parse_number(row.cells[inc_col].text)
                    if dec_col is not None and dec_col < len(row.cells):
                        decrease = _parse_number(row.cells[dec_col].text)
    if increase is None and decrease is None:
        return results

    detail_sections = [
        s for s in doc.sections
        if '변동' in (s.title or '') and ('연결대상' in (s.title or '') or '종속회사' in (s.title or ''))
    ]
    if not detail_sections:
        return results  # "변동내용" 자체가 없으면 비교 대상이 없어 판단을 보류한다

    new_count = excluded_count = 0
    for s in detail_sections:
        for table in s.tables:
            for row in table.rows:
                for cell in row.cells:
                    text = (cell.text or '').strip()
                    if text == '신규연결':
                        new_count += 1
                    elif text in ('연결제외', '연결 제외'):
                        excluded_count += 1

    if increase is not None and new_count != increase:
        results.append(RuleResult(
            rule_id='subsidiary-increase-mismatch',
            description='[연결대상 종속회사] 신규연결 건수와 증가 숫자 불일치',
            status='warn',
            detail=(
                f'"1. 개황" 표의 증가는 {increase:,.0f}건인데, "변동내용"에 나열된 신규연결 '
                f'회사는 {new_count}건입니다 — 직접 확인해주세요.'
            ),
        ))
    if decrease is not None and excluded_count != decrease:
        results.append(RuleResult(
            rule_id='subsidiary-decrease-mismatch',
            description='[연결대상 종속회사] 연결제외 건수와 감소 숫자 불일치',
            status='warn',
            detail=(
                f'"1. 개황" 표의 감소는 {decrease:,.0f}건인데, "변동내용"에 나열된 연결제외 '
                f'회사는 {excluded_count}건입니다 — 직접 확인해주세요.'
            ),
        ))
    return results


_YEAR_RE = re.compile(r'(20\d{2})\s*년')


def _detect_reporting_year(doc):
    """표지(COVER)에서 사업연도 관련 문구의 연도를 뽑아 "당기"를 추정한다.
    표지에서 못 찾으면 문서명(예: '...반기보고서 (2026.06)')에서 찾는다."""
    candidates = []
    cover = doc.section_by_key('COVER')
    if cover:
        texts = []
        for b in cover.blocks:
            if b.kind == 'table' and b.table:
                for row in b.table.rows:
                    texts.extend(c.text for c in row.cells)
            elif b.text:
                texts.append(b.text)
        for t in texts:
            candidates.extend(int(y) for y in _YEAR_RE.findall(t))
    if not candidates:
        candidates = [int(y) for y in _YEAR_RE.findall(doc.doc_name or '')]
    return max(candidates) if candidates else None


def check_history_five_years(doc) -> list:
    """"회사의 연혁"은 최근 5개년을 다뤄야 하는데, 표(보통 첫 칸이 연도)에
    당기 기준 5개년(예: 26년 반기면 22~26)이 전부 등장하는지 연도 텍스트로
    확인한다. 표기 형식(전체 4자리/2자리 축약)을 최대한 넓게 잡는다."""
    results = []
    history_sections = [s for s in doc.sections if '연혁' in (s.title or '')]
    if not history_sections:
        return results
    current_year = _detect_reporting_year(doc)
    if current_year is None:
        return results
    expected_years = [current_year - i for i in range(4, -1, -1)]

    for s in history_sections:
        found_years = set()
        label_texts = []
        for table in s.tables:
            for row in table.rows:
                if row.cells:
                    label_texts.append(row.cells[0].text)
        if not label_texts:
            label_texts = list(s.paragraphs)
        for y in expected_years:
            y2 = str(y)[2:]
            patterns = (str(y), f"'{y2}", f'{y2}년', f'{y2}.')
            for text in label_texts:
                if any(p in (text or '') for p in patterns):
                    found_years.add(y)
                    break
        missing = [y for y in expected_years if y not in found_years]
        if missing:
            missing_label = ', '.join(f'{y}년' for y in missing)
            results.append(RuleResult(
                rule_id=f'history-years-{s.key}',
                description=f'[{s.title}] 최근 5개년({expected_years[0]}~{expected_years[-1]}) 중 일부 연도 누락 의심',
                status='warn',
                detail=f'{missing_label} 관련 항목을 표에서 찾지 못했습니다 — 실제 누락인지, 표기 형식 차이로 인한 오탐인지 확인해주세요.',
            ))
    return results


_SHARE_COL_LABELS = {
    'authorized': '발행할 주식의 총수',
    'issued_total': '현재까지 발행한 주식의 총수',
    'decreased': '현재까지 감소한 주식의 총수',
    'outstanding': '발행주식의 총수',
    'treasury': '자기주식수',
    'circulating': '유통주식수',
}


def _find_share_cols(headers):
    cols = {}
    for i, h in enumerate(headers):
        if 'outstanding' not in cols and '발행주식의 총수' in h and '발행할' not in h:
            cols['outstanding'] = i
        if 'authorized' not in cols and '발행할 주식' in h:
            cols['authorized'] = i
        if 'issued_total' not in cols and '현재까지 발행한' in h:
            cols['issued_total'] = i
        if 'decreased' not in cols and '현재까지 감소한' in h:
            cols['decreased'] = i
        if 'treasury' not in cols and '자기주식' in h:
            cols['treasury'] = i
        if 'circulating' not in cols and '유통주식' in h:
            cols['circulating'] = i
    return cols


def check_share_totals_consistency(doc) -> list:
    """"4. 주식의 총수" 표(발행할/현재까지 발행한/현재까지 감소한/발행주식의
    총수/자기주식수/유통주식수)의 행별 산식과, 보통주+우선주 합이 합계 행과
    맞는지 확인한다.
      - 발행주식의 총수 = 현재까지 발행한 주식의 총수 − 현재까지 감소한 주식의 총수
      - 유통주식수 = 발행주식의 총수 − 자기주식수
      - 합계 행 = 개별 행(보통주/우선주 등)의 합
    """
    results = []
    target_sections = [s for s in doc.sections if '주식의 총수' in (s.title or '')]
    for s in target_sections:
        for t_idx, table in enumerate(s.tables):
            if len(table.rows) < 2:
                continue
            headers = _header_texts(table)
            cols = _find_share_cols(headers)
            if 'issued_total' not in cols or 'decreased' not in cols or 'outstanding' not in cols:
                continue

            header_row_count = len(_header_rows(table))
            data_rows = table.rows[header_row_count:]
            col_sums = {}
            total_row_values = None
            for row in data_rows:
                label = row.label.strip()
                is_total = label in ('합계', '계', '총계')
                row_values = {}
                for key, idx in cols.items():
                    if idx < len(row.cells):
                        row_values[key] = _parse_number(row.cells[idx].text)
                if is_total:
                    total_row_values = row_values
                    continue

                issued = row_values.get('issued_total')
                decreased = row_values.get('decreased')
                outstanding = row_values.get('outstanding')
                if issued is not None and decreased is not None and outstanding is not None:
                    expected = issued - decreased
                    if abs(expected - outstanding) > max(1.0, abs(outstanding) * 0.001):
                        results.append(RuleResult(
                            rule_id=f'shares-issued-{s.key}-{t_idx}-{label}',
                            description=f'[{s.title}] "{label}" 발행주식의 총수 산식 불일치',
                            status='warn',
                            detail=(
                                f'현재까지 발행한 주식의 총수({issued:,.0f}) − 현재까지 감소한 '
                                f'주식의 총수({decreased:,.0f}) = {expected:,.0f} 인데, 표의 '
                                f'발행주식의 총수는 {outstanding:,.0f}입니다.'
                            ),
                        ))

                treasury = row_values.get('treasury')
                circulating = row_values.get('circulating')
                if outstanding is not None and treasury is not None and circulating is not None:
                    expected2 = outstanding - treasury
                    if abs(expected2 - circulating) > max(1.0, abs(circulating) * 0.001):
                        results.append(RuleResult(
                            rule_id=f'shares-circ-{s.key}-{t_idx}-{label}',
                            description=f'[{s.title}] "{label}" 유통주식수 산식 불일치',
                            status='warn',
                            detail=(
                                f'발행주식의 총수({outstanding:,.0f}) − 자기주식수({treasury:,.0f}) '
                                f'= {expected2:,.0f} 인데, 표의 유통주식수는 {circulating:,.0f}입니다.'
                            ),
                        ))

                for key, v in row_values.items():
                    if v is not None:
                        col_sums[key] = col_sums.get(key, 0.0) + v

            if total_row_values is not None:
                for key, summed in col_sums.items():
                    total_v = total_row_values.get(key)
                    if total_v is None:
                        continue
                    if abs(summed - total_v) > max(1.0, abs(total_v) * 0.001):
                        col_label = _SHARE_COL_LABELS.get(key, key)
                        results.append(RuleResult(
                            rule_id=f'shares-sum-{s.key}-{t_idx}-{key}',
                            description=f'[{s.title}] "{col_label}" 합계 불일치',
                            status='warn',
                            detail=(
                                f'보통주+우선주 등 개별 행의 합({summed:,.0f})과 합계 행'
                                f'({total_v:,.0f})이 다릅니다.'
                            ),
                        ))
    return results
