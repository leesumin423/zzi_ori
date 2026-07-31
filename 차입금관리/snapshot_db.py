# -*- coding: utf-8 -*-
"""월별 차입금 관리내역 엑셀 스냅샷을 로컬 SQLite에 저장/조회하는 모듈.

기존에는 사용자가 매번 엑셀 파일을 업로드해야만 데이터가 화면에 표시됐지만,
이 모듈을 쓰면 '데이터 관리' 화면에서 월별로 한 번만 저장해두고
이후에는 모든 사용자가 업로드 없이 조회만 하면 됩니다.

DB 파일은 이 프로그램이 설치된 폴더의 data/snapshots.db 에 저장됩니다.
PC를 재설치/이동하지 않는 한 계속 누적되므로, 폴더 자체를 정기적으로 백업해두는 것을 권장합니다.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "snapshots.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
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


def save_snapshot(year, month, filename, file_bytes):
    """해당 연도/월의 스냅샷을 저장합니다. 이미 있으면 덮어씁니다(정정 업로드 대응)."""
    label = f"{year}년 {month}월"
    uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO snapshots (year, month, label, filename, uploaded_at, file_bytes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, month) DO UPDATE SET
                label = excluded.label,
                filename = excluded.filename,
                uploaded_at = excluded.uploaded_at,
                file_bytes = excluded.file_bytes
            """,
            (year, month, label, filename, uploaded_at, file_bytes),
        )
    conn.close()


def list_snapshots():
    """(id, year, month, label, filename, uploaded_at, size_bytes) 목록을 최신순으로 반환합니다."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT id, year, month, label, filename, uploaded_at, length(file_bytes)
        FROM snapshots
        ORDER BY year DESC, month DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_snapshot_bytes(snapshot_id):
    conn = _get_conn()
    row = conn.execute("SELECT file_bytes FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_latest_snapshot():
    """가장 최근(연도·월 기준) 스냅샷의 (id, year, month, label)을 반환합니다. 없으면 None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, year, month, label FROM snapshots ORDER BY year DESC, month DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def delete_snapshot(snapshot_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
    conn.close()
