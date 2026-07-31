# -*- coding: utf-8 -*-
"""과거 실제 이자 정산 이력(actual_interest) + 확정된 미래 이자지급 스케줄(fixed_schedule) 저장소.

담당자가 수기로 관리해온 "28일 이자.xlsx" 같은 워크북(연도별 시트에 은행별 이자계산
구간ㆍ이자금액이 정리돼 있고, PCBO처럼 특정 대출은 만기까지 확정된 지급 스케줄 시트가
별도로 있는 형태)을 업로드하면 그대로 파싱해 이 DB에 저장합니다. 예상이자 계산 화면은
- 과거 실적: 여기 저장된 actual_interest를 연도별로 그대로 보여주고(재계산 없음),
- 앞으로의 예상이자: 확정 스케줄(fixed_schedule)에 해당 구간이 있으면 그 확정 금액을,
  없으면 기존의 잔액×금리×일수/365 계산식을 그대로 씁니다.
"""
import os
import sqlite3
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "interest_history.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS actual_interest (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            bank TEXT NOT NULL,
            amount REAL,
            rate REAL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            interest REAL NOT NULL,
            source TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fixed_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_name TEXT NOT NULL,
            amount REAL,
            rate REAL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            interest REAL NOT NULL,
            note TEXT,
            source TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _coerce_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d'):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


_VALIDATION_TOLERANCE = 0.10  # 재계산 금액과 10% 넘게 어긋나면 컬럼이 잘못 읽힌 것으로 보고 버린다


def _validate_interest(amount, rate, start, end, interest):
    """principal×rate×days/365로 재계산해 저장된 이자금액과 크게 어긋나면 False.
    이 파일은 사람이 수기로 관리해온 표라 블록마다 컬럼 구성(이율/적수 유무)이 달라
    헤더를 잘못 잡으면 전혀 엉뚱한 값을 이자금액으로 읽어버릴 수 있는데, 그런 사고를
    이 검증으로 걸러낸다(실제/360 등 계산기준 차이로 인한 몇% 오차는 허용)."""
    if not isinstance(amount, (int, float)) or not isinstance(rate, (int, float)):
        return False
    if not amount or not rate or not start or not end or end <= start:
        return False
    days = (end - start).days
    expected = amount * rate * days / 365
    if expected <= 0:
        return False
    return abs(interest - expected) / expected <= _VALIDATION_TOLERANCE


def parse_interest_block_sheet(ws):
    """'은행'(또는 '일자') / [이율] / 이자계산시작 / 이자계산끝 / [적수] / 금액(이자) 형태로 된
    표를 시트 전체에서 찾아 파싱합니다. 이 파일은 사람이 수기로 관리해온 표라 같은 시트
    안에서도 구간(보통 월별)마다 헤더가 다시 나오고, 그때마다 열 구성이 미묘하게 달라질 수
    있어(예: '이율'/'적수' 컬럼이 있는 구간과 없는 구간이 섞여 있음) 헤더를 한 번만 찾지
    않고 '이자계산시작'이 보이는 행을 만날 때마다 그 행 기준으로 열 위치를 다시 잡는다.
    병합되어 비어있는 셀(같은 은행이 여러 구간으로 나뉜 경우)은 바로 위 값을 이어받고,
    재계산한 이자와 크게 다른(=열이 잘못 잡혔을 가능성이 있는) 행은 버린다.
    반환: [{'label','amount','rate','start','end','interest'}, ...]
    """
    rows = []
    label_col = amt_col = rate_col = start_col = end_col = interest_col = None
    cur_label, cur_amt, cur_rate = None, None, None

    for r in range(1, ws.max_row + 1):
        header_start_col = None
        for c in range(1, ws.max_column + 1):
            if ws.cell(row=r, column=c).value == '이자계산시작':
                header_start_col = c
                break

        if header_start_col is not None:
            start_col = header_start_col
            end_col = header_start_col + 1
            left1 = ws.cell(row=r, column=header_start_col - 1).value
            if left1 == '이율':
                rate_col = header_start_col - 1
                amt_col = header_start_col - 2
                label_col = header_start_col - 3
                interest_col = end_col + 2  # 이자계산끝, 적수, 금액
            else:
                rate_col = None
                amt_col = header_start_col - 1
                label_col = header_start_col - 2
                interest_col = end_col + 1  # 이자계산끝, 금액
            cur_label, cur_amt, cur_rate = None, None, None
            continue

        if label_col is None:
            continue  # 아직 헤더를 못 찾음

        label = ws.cell(row=r, column=label_col).value
        amt = ws.cell(row=r, column=amt_col).value
        rate = ws.cell(row=r, column=rate_col).value if rate_col else None
        start = _coerce_date(ws.cell(row=r, column=start_col).value)
        end = _coerce_date(ws.cell(row=r, column=end_col).value)
        interest = ws.cell(row=r, column=interest_col).value

        if label and str(label).strip() in ('합계', '계'):
            cur_label = None
            continue
        if start is None and end is None and amt is None and interest is None:
            continue

        if label:
            cur_label = str(label).strip()
        if amt is not None:
            cur_amt = amt
        if rate is not None:
            cur_rate = rate
        if start is None or end is None or not isinstance(interest, (int, float)):
            continue
        if not _validate_interest(cur_amt, cur_rate, start, end, interest):
            continue

        rows.append({
            'label': cur_label, 'amount': cur_amt, 'rate': cur_rate,
            'start': start, 'end': end, 'interest': interest,
        })
    return rows


def import_from_workbook(wb, source=None):
    """워크북에서 4자리 연도 이름의 시트는 실적(actual_interest)으로, 이름에 '이자지급일정'이
    들어간 시트는 확정 스케줄(fixed_schedule)로 각각 저장합니다(같은 이름으로 다시 올리면
    그 연도/대출명 데이터를 지우고 새로 채웁니다 — 재업로드 시 중복 방지).
    반환: {'years': {연도: 건수}, 'schedules': {대출명: 건수}}
    """
    result = {'years': {}, 'schedules': {}}
    for name in wb.sheetnames:
        stripped = name.strip()
        if stripped.isdigit() and len(stripped) == 4:
            parsed = parse_interest_block_sheet(wb[name])
            if not parsed:
                continue
            year = int(stripped)
            replace_actual_interest_for_year(
                year,
                [{'bank': r['label'], 'amount': r['amount'], 'rate': r['rate'],
                  'start': r['start'], 'end': r['end'], 'interest': r['interest']} for r in parsed],
                source=source,
            )
            result['years'][year] = len(parsed)
        elif '이자지급일정' in stripped:
            parsed = parse_interest_block_sheet(wb[name])
            if not parsed:
                continue
            loan_name = stripped.split(' ')[0].strip() or stripped
            replace_fixed_schedule_for_loan(
                loan_name,
                [{'amount': r['amount'], 'rate': r['rate'],
                  'start': r['start'], 'end': r['end'], 'interest': r['interest']} for r in parsed],
                source=source,
            )
            result['schedules'][loan_name] = len(parsed)
    return result


def replace_actual_interest_for_year(year, rows, source=None):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM actual_interest WHERE year = ?", (year,))
        conn.executemany(
            "INSERT INTO actual_interest (year, bank, amount, rate, period_start, period_end, interest, source, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (year, r['bank'], r['amount'], r['rate'], r['start'].isoformat(), r['end'].isoformat(),
                 r['interest'], source, _now())
                for r in rows
            ],
        )
    conn.close()


def list_actual_interest(year=None):
    conn = _get_conn()
    if year is not None:
        rows = conn.execute(
            "SELECT year, bank, amount, rate, period_start, period_end, interest "
            "FROM actual_interest WHERE year = ? ORDER BY period_start", (year,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT year, bank, amount, rate, period_start, period_end, interest "
            "FROM actual_interest ORDER BY year, period_start"
        ).fetchall()
    conn.close()
    return rows


def list_actual_interest_years():
    conn = _get_conn()
    rows = conn.execute("SELECT DISTINCT year FROM actual_interest ORDER BY year DESC").fetchall()
    conn.close()
    return [r[0] for r in rows]


def replace_fixed_schedule_for_loan(loan_name, rows, source=None):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM fixed_schedule WHERE loan_name = ?", (loan_name,))
        conn.executemany(
            "INSERT INTO fixed_schedule (loan_name, amount, rate, period_start, period_end, interest, note, source, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (loan_name, r.get('amount'), r.get('rate'), r['start'].isoformat(), r['end'].isoformat(),
                 r['interest'], r.get('note'), source, _now())
                for r in rows
            ],
        )
    conn.close()


def add_fixed_schedule_row(loan_name, amount, rate, period_start, period_end, interest, note=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO fixed_schedule (loan_name, amount, rate, period_start, period_end, interest, note, source, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (loan_name, amount, rate, period_start.isoformat(), period_end.isoformat(), interest, note, '직접입력', _now()),
        )
    conn.close()


def delete_fixed_schedule_loan(loan_name):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM fixed_schedule WHERE loan_name = ?", (loan_name,))
    conn.close()


def delete_fixed_schedule_row(row_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM fixed_schedule WHERE id = ?", (row_id,))
    conn.close()


def list_fixed_schedule(loan_name=None):
    conn = _get_conn()
    if loan_name:
        rows = conn.execute(
            "SELECT id, loan_name, amount, rate, period_start, period_end, interest, note "
            "FROM fixed_schedule WHERE loan_name = ? ORDER BY period_start", (loan_name,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, loan_name, amount, rate, period_start, period_end, interest, note "
            "FROM fixed_schedule ORDER BY loan_name, period_start"
        ).fetchall()
    conn.close()
    return rows


def list_fixed_schedule_loan_names():
    conn = _get_conn()
    rows = conn.execute("SELECT DISTINCT loan_name FROM fixed_schedule ORDER BY loan_name").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_fixed_schedule_interest_for_period(loan_name, period_start, period_end):
    """예상이자 계산 중인 구간(period_start~period_end)과 정확히 일치하는 확정 스케줄
    행이 있으면 그 이자금액을, 없으면 None을 반환합니다(호출부는 None이면 기존 계산식을
    그대로 씁니다 — 확정 스케줄은 '있으면 그것만 대체'하는 보강 데이터입니다)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT interest FROM fixed_schedule WHERE loan_name = ? AND period_start = ? AND period_end = ?",
        (loan_name, period_start.isoformat(), period_end.isoformat()),
    ).fetchone()
    conn.close()
    return row[0] if row else None
