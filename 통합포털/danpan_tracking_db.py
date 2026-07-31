# -*- coding: utf-8 -*-
"""단판공시(단일판매ㆍ공급계약체결) 현장별 담당부서/담당자 메모 + 월별 스냅샷 저장소.

- site_meta: DART에는 없는 "이 현장은 어느 부서/담당자가 관리하는지"를 자금팀이
  직접 입력해두는 표 — 메일에 현장별 담당부서를 표시해서 받는 사람이 자기 현장을
  바로 알아보고 변동내역을 회신할 수 있게 하기 위함입니다.
- monthly_snapshot: 메일을 보낼 때마다 그 시점의 현장 목록을 그대로 저장해두고,
  다음 달 발송 때 이전 스냅샷과 비교해 "전월 대비 무엇이 바뀌었는지"를 자동으로
  뽑아내는 데 씁니다(신규/금액변경/기간변경/정정공시/관리종료).
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hub.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS danpan_site_meta (
            site_name TEXT PRIMARY KEY,
            department TEXT,
            manager TEXT,
            note TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    # 담당자의 상위자(부서장 등)를 CC로 같이 받게 하려는 요청 — 그룹웨어 조직도를
    # 크롤링하는 대신, 현장별로 CC 받을 사람 이메일을 자금팀이 직접 입력해두는
    # 방식으로 단순화했다(그룹웨어 로그인 크롤링은 세션 만료ㆍ속도 등 발송 자체가
    # 실패할 위험이 있어 보류).
    for column, coldef in [("cc_email", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE danpan_site_meta ADD COLUMN {column} {coldef}")
        except sqlite3.OperationalError:
            pass
    # 특정 현장에 매이지 않고 항상 참조로 받아야 하는 사람(예: 자금팀 담당팀장).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS danpan_mail_fixed_cc (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            label TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS danpan_monthly_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year_month TEXT NOT NULL,
            site_name TEXT NOT NULL,
            counterparty TEXT,
            amount REAL,
            initial_contract_date TEXT,
            latest_disclosure_date TEXT,
            revision_count INTEGER,
            period_start TEXT,
            period_end TEXT,
            dart_url TEXT,
            captured_at TEXT NOT NULL
        )
        """
    )
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 현장별 담당부서/담당자 메모 ──────────────────────────────

def get_all_site_meta():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT site_name, department, manager, note, cc_email FROM danpan_site_meta"
    ).fetchall()
    conn.close()
    return {r[0]: {"department": r[1], "manager": r[2], "note": r[3], "cc_email": r[4]} for r in rows}


def set_site_meta(site_name, department, manager, note, cc_email=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO danpan_site_meta (site_name, department, manager, note, cc_email, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(site_name) DO UPDATE SET department=excluded.department, "
            "manager=excluded.manager, note=excluded.note, cc_email=excluded.cc_email, "
            "updated_at=excluded.updated_at",
            (site_name, department, manager, note, cc_email, _now()),
        )
    conn.close()


def delete_site_meta(site_name):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM danpan_site_meta WHERE site_name = ?", (site_name,))
    conn.close()


# ── 고정 CC(현장과 무관하게 항상 참조로 받는 사람, 예: 자금팀 담당팀장) ──────

def list_fixed_cc():
    conn = _get_conn()
    rows = conn.execute("SELECT id, email, label FROM danpan_mail_fixed_cc ORDER BY id").fetchall()
    conn.close()
    return rows


def add_fixed_cc(email, label=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO danpan_mail_fixed_cc (email, label, created_at) VALUES (?, ?, ?)",
            (email, label, _now()),
        )
    conn.close()


def delete_fixed_cc(cc_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM danpan_mail_fixed_cc WHERE id = ?", (cc_id,))
    conn.close()


# ── 월별 스냅샷 ──────────────────────────────────────────────

def save_snapshot(year_month, sites):
    """같은 달에 다시 저장하면(같은 달에 두 번 발송 등) 그 달 것만 지우고 새로 채운다."""
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM danpan_monthly_snapshot WHERE year_month = ?", (year_month,))
        conn.executemany(
            "INSERT INTO danpan_monthly_snapshot "
            "(year_month, site_name, counterparty, amount, initial_contract_date, latest_disclosure_date, "
            "revision_count, period_start, period_end, dart_url, captured_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    year_month, s.get('site_name'), s.get('counterparty'), s.get('amount'),
                    s.get('initial_contract_date'), s.get('latest_disclosure_date'),
                    s.get('revision_count'), s.get('period_start'), s.get('period_end'),
                    s.get('dart_url'), _now(),
                )
                for s in sites
            ],
        )
    conn.close()


def get_latest_snapshot_before(year_month):
    """year_month보다 이전(작은) 스냅샷 중 가장 최근 것을 {site_name: row_dict}로 반환.
    없으면 빈 dict(=비교 대상 없음, 첫 발송으로 취급)."""
    conn = _get_conn()
    prev_ym = conn.execute(
        "SELECT DISTINCT year_month FROM danpan_monthly_snapshot WHERE year_month < ? "
        "ORDER BY year_month DESC LIMIT 1",
        (year_month,),
    ).fetchone()
    if not prev_ym:
        conn.close()
        return {}
    rows = conn.execute(
        "SELECT site_name, counterparty, amount, initial_contract_date, latest_disclosure_date, "
        "revision_count, period_start, period_end, dart_url FROM danpan_monthly_snapshot WHERE year_month = ?",
        (prev_ym[0],),
    ).fetchall()
    conn.close()
    cols = ['site_name', 'counterparty', 'amount', 'initial_contract_date', 'latest_disclosure_date',
            'revision_count', 'period_start', 'period_end', 'dart_url']
    return {r[0]: dict(zip(cols, r)) for r in rows}
