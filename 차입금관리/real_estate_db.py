# -*- coding: utf-8 -*-
"""(주)동양 부동산(담보 가능 자산) 현황 저장소.

팀에서 별도 엑셀("★ (주)동양 부동산 현황_2025_최신.xlsx")로 관리해온 사업장별 부동산
장부가ㆍ감정평가액ㆍ담보제공 현황을 그대로 옮겨와 담보현황 화면에서 같이 보여주기
위한 모듈입니다. 차입금 데이터(monthly snapshot)와는 별개의 데이터 소스라 독립된
표(테이블)로 저장하고, 업로드(엑셀 파싱)와 화면에서 직접 수정 둘 다 지원합니다.
"""
import os
import sqlite3
import uuid
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "real_estate.db")
DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "re_documents")

COLUMNS = [
    "category", "site_name", "land_value", "building_value", "subtotal_value",
    "appraisal_value", "appraisal_year", "bank", "collateral_detail", "note", "biz_unit",
    "approval_doc_url",
]

DOC_TYPES = ["근저당권설정계약서", "등기필증(등기사항증명서)", "채권최고액 확인서류", "품의서 사본", "기타"]


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS real_estate_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            site_name TEXT NOT NULL,
            land_value REAL,
            building_value REAL,
            subtotal_value REAL,
            appraisal_value REAL,
            appraisal_year TEXT,
            bank TEXT,
            collateral_detail TEXT,
            note TEXT,
            biz_unit TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS real_estate_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS real_estate_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            land_value REAL,
            building_value REAL,
            subtotal_value REAL,
            appraisal_value REAL,
            land_ratio REAL,
            building_ratio REAL,
            subtotal_ratio REAL,
            note TEXT,
            sort_order INTEGER,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS real_estate_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            note TEXT,
            uploaded_by TEXT,
            uploaded_at TEXT NOT NULL
        )
        """
    )
    try:
        conn.execute("ALTER TABLE real_estate_sites ADD COLUMN approval_doc_url TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_real_estate_workbook(wb, sheet_name="담보현황_사업장별"):
    """'담보현황_사업장별' 시트(업무용/비업무용 두 블록, 구조 동일)를 파싱합니다.
    " - 업무용"/" - 비업무용" 같은 구분 라벨 행으로 category를 갱신해가며, 사업장명
    (C열)이 채워진 행만 실제 데이터로 채택합니다 — 상단 요약표ㆍ소계행ㆍ헤더행은
    전부 C열이 비어있어 자동으로 걸러집니다.
    반환: [{"category","site_name","land_value",...}, ...]
    """
    if sheet_name not in wb.sheetnames:
        return []
    ws = wb[sheet_name]

    rows = []
    category = None
    for r in range(1, ws.max_row + 1):
        label = ws.cell(row=r, column=2).value
        if isinstance(label, str) and label.strip().startswith('-'):
            category = label.strip().lstrip('-').strip()
            continue

        site_name = ws.cell(row=r, column=3).value
        subtotal = ws.cell(row=r, column=6).value
        if not site_name or not category or not isinstance(subtotal, (int, float)):
            continue

        rows.append({
            "category": category,
            "site_name": str(site_name).strip(),
            "land_value": ws.cell(row=r, column=4).value,
            "building_value": ws.cell(row=r, column=5).value,
            "subtotal_value": subtotal,
            "appraisal_value": ws.cell(row=r, column=7).value,
            "appraisal_year": ws.cell(row=r, column=8).value,
            "bank": ws.cell(row=r, column=9).value,
            "collateral_detail": ws.cell(row=r, column=10).value,
            "note": ws.cell(row=r, column=11).value,
            "biz_unit": ws.cell(row=r, column=13).value,
        })
    return rows


def parse_real_estate_summary(wb, sheet_name="담보현황_사업장별"):
    """시트 상단의 '담보 제공中/담보 불가/담보 가능/합계' 요약표(토지ㆍ건물ㆍ소계ㆍ감평가 +
    비율)를 그대로 읽어옵니다. 고정 셀 좌표 대신 '구분'/'금액' 헤더 행을 찾아 상대
    위치로 읽으므로, 표가 몇 행 밀려도 그대로 찾습니다."""
    if sheet_name not in wb.sheetnames:
        return []
    ws = wb[sheet_name]
    header_row = None
    for r in range(1, min(ws.max_row, 20) + 1):
        if ws.cell(row=r, column=2).value == '구분' and ws.cell(row=r, column=4).value == '금액':
            header_row = r
            break
    if header_row is None:
        return []

    rows = []
    for r in range(header_row + 1, header_row + 10):
        label = ws.cell(row=r, column=2).value
        subtotal = ws.cell(row=r, column=6).value
        if not (isinstance(label, str) and label.strip()) or not isinstance(subtotal, (int, float)):
            continue
        rows.append({
            "label": label.strip(),
            "land_value": ws.cell(row=r, column=4).value,
            "building_value": ws.cell(row=r, column=5).value,
            "subtotal_value": subtotal,
            "appraisal_value": ws.cell(row=r, column=7).value,
            "land_ratio": ws.cell(row=r, column=13).value,
            "building_ratio": ws.cell(row=r, column=14).value,
            "subtotal_ratio": ws.cell(row=r, column=15).value,
            "note": ws.cell(row=r, column=8).value,
        })
        if label.strip() == '합계':
            break
    return rows


def replace_summary(rows, source=None):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM real_estate_summary")
        conn.executemany(
            "INSERT INTO real_estate_summary "
            "(label, land_value, building_value, subtotal_value, appraisal_value, "
            "land_ratio, building_ratio, subtotal_ratio, note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r["label"], r.get("land_value"), r.get("building_value"), r.get("subtotal_value"),
                    r.get("appraisal_value"), r.get("land_ratio"), r.get("building_ratio"),
                    r.get("subtotal_ratio"), r.get("note"), i, _now(),
                )
                for i, r in enumerate(rows)
            ],
        )
    conn.close()


def list_summary():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT label, land_value, building_value, subtotal_value, appraisal_value, "
        "land_ratio, building_ratio, subtotal_ratio, note FROM real_estate_summary ORDER BY sort_order"
    ).fetchall()
    conn.close()
    cols = ["label", "land_value", "building_value", "subtotal_value", "appraisal_value",
            "land_ratio", "building_ratio", "subtotal_ratio", "note"]
    return [dict(zip(cols, r)) for r in rows]


def replace_all_sites(rows, source=None):
    """업로드/전체 재입력 시 기존 데이터를 지우고 통째로 교체합니다.

    사업장 행은 매번 삭제 후 새 id로 다시 들어가지만, 품의서 링크(approval_doc_url)와
    업로드해둔 담보 서류(real_estate_documents.site_id)는 site_name으로 매칭해 새 id로
    이어붙여서 재업로드해도 잃어버리지 않게 한다.
    """
    conn = _get_conn()
    with conn:
        old = conn.execute("SELECT id, site_name, approval_doc_url FROM real_estate_sites").fetchall()
        old_url_by_name = {name: url for _id, name, url in old if url}
        old_id_by_name = {}
        for _id, name, _url in old:
            old_id_by_name.setdefault(name, []).append(_id)

        conn.execute("DELETE FROM real_estate_sites")
        for r in rows:
            if not r.get("approval_doc_url"):
                r["approval_doc_url"] = old_url_by_name.get(r.get("site_name"))
        conn.executemany(
            f"INSERT INTO real_estate_sites ({', '.join(COLUMNS)}, updated_at) "
            f"VALUES ({', '.join(['?'] * len(COLUMNS))}, ?)",
            [tuple(r.get(c) for c in COLUMNS) + (_now(),) for r in rows],
        )

        new_rows = conn.execute("SELECT id, site_name FROM real_estate_sites").fetchall()
        new_id_by_name = {}
        for _id, name in new_rows:
            new_id_by_name.setdefault(name, []).append(_id)
        remap = {}
        for name, old_ids in old_id_by_name.items():
            new_ids = new_id_by_name.get(name)
            if not new_ids:
                continue
            for i, old_id in enumerate(old_ids):
                new_id = new_ids[i] if i < len(new_ids) else new_ids[-1]
                if new_id != old_id:
                    remap[old_id] = new_id
        # old_id/new_id 범위가 겹치는 동일 auto-increment 시퀀스라 순서대로 바로
        # UPDATE하면 이미 옮겨놓은 값을 다음 짝이 다시 덮어쓸 수 있다 — 음수로
        # 한번 대피시켰다가 마지막에 부호를 되돌리는 2단계로 충돌을 피한다.
        for old_id, new_id in remap.items():
            conn.execute(
                "UPDATE real_estate_documents SET site_id = ? WHERE site_id = ?",
                (-new_id, old_id),
            )
        conn.execute(
            "UPDATE real_estate_documents SET site_id = -site_id WHERE site_id < 0"
        )

        if source:
            conn.execute(
                "INSERT INTO real_estate_meta (key, value) VALUES ('source', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (source,),
            )
        conn.execute(
            "INSERT INTO real_estate_meta (key, value) VALUES ('updated_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_now(),),
        )
    conn.close()


def list_sites():
    conn = _get_conn()
    rows = conn.execute(
        f"SELECT id, {', '.join(COLUMNS)} FROM real_estate_sites ORDER BY "
        "CASE category WHEN '업무용' THEN 0 ELSE 1 END, id"
    ).fetchall()
    conn.close()
    cols = ["id"] + COLUMNS
    return [dict(zip(cols, r)) for r in rows]


def update_site(site_id, **fields):
    valid = {k: v for k, v in fields.items() if k in COLUMNS}
    if not valid:
        return
    conn = _get_conn()
    with conn:
        set_clause = ", ".join(f"{k} = ?" for k in valid)
        conn.execute(
            f"UPDATE real_estate_sites SET {set_clause}, updated_at = ? WHERE id = ?",
            list(valid.values()) + [_now(), site_id],
        )
    conn.close()


def add_site(**fields):
    conn = _get_conn()
    with conn:
        cols = [c for c in COLUMNS if c in fields]
        conn.execute(
            f"INSERT INTO real_estate_sites ({', '.join(cols)}, updated_at) "
            f"VALUES ({', '.join(['?'] * len(cols))}, ?)",
            [fields[c] for c in cols] + [_now()],
        )
    conn.close()


def delete_site(site_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM real_estate_sites WHERE id = ?", (site_id,))
    conn.close()


def get_meta(key):
    conn = _get_conn()
    row = conn.execute("SELECT value FROM real_estate_meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None


def add_document(site_id, doc_type, original_filename, file_bytes, uploaded_by=None, note=None):
    """담보 물건지에 딸린 서류(근저당권설정계약서ㆍ등기필증ㆍ채권최고액 확인서류 등)를
    저장합니다. 실제 파일은 DOCS_DIR에 uuid 이름으로 저장하고(원본 파일명 충돌 방지),
    DB엔 메타데이터만 남깁니다."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    ext = os.path.splitext(original_filename)[1]
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(DOCS_DIR, stored_filename), "wb") as f:
        f.write(file_bytes)
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO real_estate_documents "
            "(site_id, doc_type, original_filename, stored_filename, note, uploaded_by, uploaded_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (site_id, doc_type, original_filename, stored_filename, note, uploaded_by, _now()),
        )
    conn.close()


def list_documents(site_id):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, doc_type, original_filename, stored_filename, note, uploaded_by, uploaded_at "
        "FROM real_estate_documents WHERE site_id = ? ORDER BY uploaded_at DESC",
        (site_id,),
    ).fetchall()
    conn.close()
    cols = ["id", "doc_type", "original_filename", "stored_filename", "note", "uploaded_by", "uploaded_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_document_file(doc_id):
    """(원본 파일명, 파일 bytes) 반환 — 없으면 None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT original_filename, stored_filename FROM real_estate_documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    original_filename, stored_filename = row
    path = os.path.join(DOCS_DIR, stored_filename)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return original_filename, f.read()


def delete_document(doc_id):
    conn = _get_conn()
    row = conn.execute("SELECT stored_filename FROM real_estate_documents WHERE id = ?", (doc_id,)).fetchone()
    with conn:
        conn.execute("DELETE FROM real_estate_documents WHERE id = ?", (doc_id,))
    conn.close()
    if row:
        path = os.path.join(DOCS_DIR, row[0])
        if os.path.exists(path):
            os.remove(path)
