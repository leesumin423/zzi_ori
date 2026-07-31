# -*- coding: utf-8 -*-
"""부수거래(예금 기여도ㆍ법인카드 사용금액) 엑셀을 로컬 SQLite에 저장/조회하는 모듈.

이 두 파일은 월별 스냅샷이 아니라 "현재 기준 최신 전체 이력"을 담은 단일 파일이라
(파일 하나에 연도별 데이터가 다 들어있음) snapshot_db.py처럼 날짜별로 여러 건을
쌓지 않고, 종류(kind: 'deposit'/'card')별로 딱 한 건만 최신 상태로 덮어쓴다.

예전에는 st.session_state에만 올려뒀었는데, 그러면 서버가 재시작되거나 다른
사용자가 접속하면 업로드한 파일이 사라져서(=" 플래시되어 날아간다") 매번 다시
올려야 했다. 이제 여기 저장해두면 재시작해도, 다른 사용자가 봐도 그대로 남는다."""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ancillary_files.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ancillary_files (
            kind TEXT PRIMARY KEY,
            filename TEXT,
            uploaded_at TEXT NOT NULL,
            file_bytes BLOB NOT NULL
        )
        """
    )
    return conn


def save_file(kind, filename, file_bytes):
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO ancillary_files (kind, filename, uploaded_at, file_bytes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind) DO UPDATE SET
                filename = excluded.filename,
                uploaded_at = excluded.uploaded_at,
                file_bytes = excluded.file_bytes
            """,
            (kind, filename, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), file_bytes),
        )
    conn.close()


def get_file(kind):
    """(filename, uploaded_at, file_bytes) 또는 등록된 게 없으면 None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT filename, uploaded_at, file_bytes FROM ancillary_files WHERE kind = ?", (kind,)
    ).fetchone()
    conn.close()
    return row


def delete_file(kind):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM ancillary_files WHERE kind = ?", (kind,))
    conn.close()
