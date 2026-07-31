# -*- coding: utf-8 -*-
"""그룹 차입금 보고서(법인별 월간 업로드분)를 로컬 SQLite에 저장/조회하는 모듈.
monthly_report_db.py와 같은 패턴이지만 (year, month) 대신 (company, year, month)가
키다 — 법인마다 따로 매월 업로드하기 때문."""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "group_loan_reports.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_loan_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            filename TEXT,
            uploaded_at TEXT NOT NULL,
            file_bytes BLOB NOT NULL,
            UNIQUE(company, year, month)
        )
        """
    )
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_report(company, year, month, filename, file_bytes):
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO group_loan_reports (company, year, month, filename, uploaded_at, file_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(company, year, month) DO UPDATE SET
                filename = excluded.filename,
                uploaded_at = excluded.uploaded_at,
                file_bytes = excluded.file_bytes
            """,
            (company, year, month, filename, _now(), file_bytes),
        )
    conn.close()


def list_months():
    """등록된 (year, month) 조합을 최신순으로 반환한다(법인 구분 없이 조회 가능한 월 목록)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT year, month FROM group_loan_reports ORDER BY year DESC, month DESC"
    ).fetchall()
    conn.close()
    return rows


def list_reports_for_month(year, month):
    """(id, company, filename, uploaded_at, size_bytes) — 해당 월에 등록된 법인들."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT id, company, filename, uploaded_at, length(file_bytes)
        FROM group_loan_reports WHERE year = ? AND month = ?
        ORDER BY company
        """,
        (year, month),
    ).fetchall()
    conn.close()
    return rows


def get_report_bytes_by_company_month(company, year, month):
    conn = _get_conn()
    row = conn.execute(
        "SELECT file_bytes FROM group_loan_reports WHERE company = ? AND year = ? AND month = ?",
        (company, year, month),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def delete_report(report_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM group_loan_reports WHERE id = ?", (report_id,))
    conn.close()
