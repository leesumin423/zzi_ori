# -*- coding: utf-8 -*-
"""월간보고서(자금현황 통합/사업본부/대여금/자금운용/차입금·담보/어음현황 등 여러 시트를
한 파일에 담은 엑셀) 원본을 월별로 로컬 SQLite에 저장/조회하는 모듈.

snapshot_db.py(분기별 차입금 관리내역)와 같은 패턴이지만, 이건 "월" 단위이고 파일 하나에
여러 화면(표지/관리/대여/운용/차입/기타)이 들어있다는 점이 다릅니다.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "monthly_reports.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            label TEXT NOT NULL,
            filename TEXT,
            uploaded_at TEXT NOT NULL,
            file_bytes BLOB NOT NULL,
            UNIQUE(year, month)
        )
        """
    )
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_report(year, month, filename, file_bytes):
    """해당 연도/월의 월간보고서를 저장합니다. 이미 있으면 덮어씁니다(정정 업로드 대응)."""
    label = f"{year}년 {month:02d}월"
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO monthly_reports (year, month, label, filename, uploaded_at, file_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, month) DO UPDATE SET
                label = excluded.label,
                filename = excluded.filename,
                uploaded_at = excluded.uploaded_at,
                file_bytes = excluded.file_bytes
            """,
            (year, month, label, filename, _now(), file_bytes),
        )
    conn.close()


def list_reports():
    """(id, year, month, label, filename, uploaded_at, size_bytes) 목록을 최신순으로 반환합니다."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT id, year, month, label, filename, uploaded_at, length(file_bytes)
        FROM monthly_reports
        ORDER BY year DESC, month DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_report_bytes(report_id):
    conn = _get_conn()
    row = conn.execute("SELECT file_bytes FROM monthly_reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_latest_report():
    """가장 최근(연도·월 기준) 보고서의 (id, year, month, label)을 반환합니다. 없으면 None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, year, month, label FROM monthly_reports ORDER BY year DESC, month DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def delete_report(report_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM monthly_reports WHERE id = ?", (report_id,))
    conn.close()
