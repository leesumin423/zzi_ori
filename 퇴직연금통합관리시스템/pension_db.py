# -*- coding: utf-8 -*-
"""퇴직연금 현황 엑셀을 기준일자별로 로컬 SQLite에 저장/조회하는 모듈.

차입금관리의 monthly_report_db.py와 같은 패턴이다 — 예전에는 parse_data.py 안의
BASE_DATES 딕셔너리에 "기준일 → 이 PC의 엑셀 경로"를 하드코딩해두고 서버 시작
시 한 번만 읽었는데, 그러면 새 기준일을 추가할 때마다 코드를 고쳐야 하고 서버를
재시작해야 한다. 이 모듈로 등록해두면 관리자가 화면에서 업로드하는 즉시 반영된다.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pension_reports.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pension_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_date TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            sheet_hint TEXT,
            filename TEXT,
            uploaded_at TEXT NOT NULL,
            file_bytes BLOB NOT NULL
        )
        """
    )
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_report(base_date, label, sheet_hint, filename, file_bytes):
    """기준일(base_date, 'YYYY-MM-DD')의 퇴직연금 현황 엑셀을 저장한다. 이미 있으면
    덮어쓴다(정정 업로드 대응)."""
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO pension_reports (base_date, label, sheet_hint, filename, uploaded_at, file_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(base_date) DO UPDATE SET
                label = excluded.label,
                sheet_hint = excluded.sheet_hint,
                filename = excluded.filename,
                uploaded_at = excluded.uploaded_at,
                file_bytes = excluded.file_bytes
            """,
            (base_date, label, sheet_hint, filename, _now(), file_bytes),
        )
    conn.close()


def list_reports():
    """(id, base_date, label, sheet_hint, filename, uploaded_at, size_bytes) 목록을
    기준일 최신순으로 반환한다."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT id, base_date, label, sheet_hint, filename, uploaded_at, length(file_bytes)
        FROM pension_reports
        ORDER BY base_date DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_report_bytes(report_id):
    conn = _get_conn()
    row = conn.execute("SELECT file_bytes FROM pension_reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def delete_report(report_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM pension_reports WHERE id = ?", (report_id,))
    conn.close()
