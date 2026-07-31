# -*- coding: utf-8 -*-
"""통합포털 사용자·접근요청을 저장하는 로컬 SQLite 모듈.

- users: 실제 로그인 가능한 계정 (관리자가 승인해서 만든 계정만 존재)
- access_requests: '접근 요청' 화면에서 들어온 요청 (관리자가 승인/거절)

승인(approve) 시 access_requests 행이 users 행으로 바뀌는 구조입니다.
"""
import sqlite3
import os
import secrets
import string
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hub.db")


def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            display_name TEXT,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at TEXT NOT NULL,
            decided_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    # 팀별 화면(주가/공시/자금/퇴직연금) 접근권한 — 팀에 이 표에 행이 하나도 없으면
    # "아직 설정 안 함" = 전체 허용(기존 동작 그대로)으로 취급하고, 행이 하나라도
    # 있으면 그 팀은 여기 있는 section만 볼 수 있다(화이트리스트).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_permissions (
            team TEXT NOT NULL,
            section TEXT NOT NULL,
            PRIMARY KEY (team, section)
        )
        """
    )
    # 개인별 접근권한 — 임원ㆍ팀장처럼 소속 팀 설정과 상관없이 이 사람만 따로 열어줘야
    # 하는 경우용. user_id에 이 표의 행이 하나라도 있으면 팀 설정은 무시하고 이 사람의
    # 행만 본다(팀 설정보다 우선). 행이 없으면(기본값) 팀 설정을 그대로 따른다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id INTEGER NOT NULL,
            section TEXT NOT NULL,
            PRIMARY KEY (user_id, section)
        )
        """
    )
    # 단판공시(단일판매ㆍ공급계약체결) 월별 모니터링 메일 수신자 목록 — 발신자는
    # 계정 고정(박시환)이라 여기엔 수신자만 저장한다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS danpan_mail_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            label TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    # 매월 자동발송이 같은 달에 중복 발송되지 않도록 발송 이력을 남긴다(수동 발송도
    # 같이 기록 — 관리 화면에서 "마지막 발송" 확인용).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS danpan_mail_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year_month TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            recipient_count INTEGER NOT NULL,
            site_count INTEGER,
            triggered_by TEXT NOT NULL
        )
        """
    )
    # 전체 관리자 권한 없이 "단판공시 메일링 설정"만 직접 관리할 수 있는 담당자
    # (예: 공시 담당자) — 계정 승인/사용자 관리 등 나머지 관리자 화면은 볼 수 없다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS danpan_mail_admins (
            user_id INTEGER PRIMARY KEY,
            granted_at TEXT NOT NULL
        )
        """
    )
    # 월간보고서 "자금수지" 3개월 자금계획 요청 메일링 — 매월 관련 부서/담당자에게
    # 3개월 자금계획 서식(레미콘·건자재·동양공통 / 플랜트 / 건설)을 첨부해 협조전
    # 형태로 발송한다. danpan_mail_* 과 동일한 구조(수신자/발송이력/전담권한)를 그대로
    # 따른다 — 발신자(담당자)가 아직 정해지지 않아 전담권한 부여도 나중에 한다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cashflow_plan_mail_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            label TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cashflow_plan_mail_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year_month TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            recipient_count INTEGER NOT NULL,
            triggered_by TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cashflow_plan_mail_admins (
            user_id INTEGER PRIMARY KEY,
            granted_at TEXT NOT NULL
        )
        """
    )
    # 첨부할 3개 자금계획 서식 파일(레미콘·건자재·동양공통 / 플랜트 / 건설) — 매달
    # 제목의 날짜 범위(예: "2026년 08월~10월")를 담당자가 직접 갱신해서 재업로드하는
    # 구조. slot으로 구분해 각 서식을 덮어쓴다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cashflow_plan_templates (
            slot TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_blob BLOB NOT NULL,
            uploaded_by TEXT,
            uploaded_at TEXT NOT NULL
        )
        """
    )
    # 공정위 공시대상기업집단 대규모내부거래(상품ㆍ용역거래) 취합요청 협조전 —
    # cashflow_plan_mail_* 과 완전히 같은 구조(수신자/발송이력/전담권한/첨부서식).
    # 다만 참조자에 "팀명"뿐 아니라 "부서 직급 이름" 형태의 개인도 섞여 들어간다
    # (실제 협조전 샘플이 그랬다) — RPA 쪽에서 이를 구분해 처리한다.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ftc_disclosure_mail_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            label TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ftc_disclosure_mail_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_label TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            recipient_count INTEGER NOT NULL,
            triggered_by TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ftc_disclosure_mail_admins (
            user_id INTEGER PRIMARY KEY,
            granted_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ftc_disclosure_templates (
            slot TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_blob BLOB NOT NULL,
            uploaded_by TEXT,
            uploaded_at TEXT NOT NULL
        )
        """
    )
    # 기존에 만들어진 DB 파일에도 새 컬럼이 반영되도록, 이미 있으면 조용히 무시합니다.
    for table, column, coldef in [
        ("users", "email", "TEXT"),
        ("users", "team", "TEXT"),
        ("access_requests", "team", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
        except sqlite3.OperationalError:
            pass
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_bootstrap_admin(username, password, display_name="관리자"):
    """계정이 하나도 없을 때만, 최초 관리자 계정을 자동 생성합니다."""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
            (username, generate_password_hash(password), display_name, _now()),
        )
        conn.commit()
    conn.close()


def verify_login(username, password):
    """로그인 성공 시 사용자 dict, 실패 시 None을 반환합니다."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, username, password_hash, display_name, is_admin, email, team FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if row and check_password_hash(row[2], password):
        return {
            "id": row[0], "username": row[1], "display_name": row[3], "is_admin": bool(row[4]),
            "email": row[5], "team": row[6],
        }
    return None


def get_user_by_id(user_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, username, display_name, is_admin, email, team FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "username": row[1], "display_name": row[2], "is_admin": bool(row[3]),
        "email": row[4], "team": row[5],
    }


def get_user_by_username(username):
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, username, display_name, is_admin, email, team FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "username": row[1], "display_name": row[2], "is_admin": bool(row[3]),
        "email": row[4], "team": row[5],
    }


def list_users():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, username, display_name, is_admin, created_at, team, email FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return rows


def verify_password(user_id, password):
    conn = _get_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return bool(row) and check_password_hash(row[0], password)


def change_password(user_id, new_password):
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id),
        )
    conn.close()


def update_profile(user_id, team, email):
    """본인 '내 정보' 화면에서 팀/메일을 직접 수정할 수 있게 합니다.
    팀은 항목별 접근권한(뷰 제한)의 기준이므로 정확히 입력해둬야 합니다."""
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE users SET team = ?, email = ? WHERE id = ?",
            (team, email, user_id),
        )
    conn.close()


def list_distinct_teams():
    """실제 사용자가 하나라도 속한 팀 이름 목록(가나다순) — 접근권한 설정 화면에서
    행 목록으로 쓴다. 팀이 비어있는(NULL/'') 계정은 제외한다."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT team FROM users WHERE team IS NOT NULL AND team != '' ORDER BY team"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_team_permissions(team):
    """이 팀에 허용된 section id 집합을 반환합니다. 그 팀에 설정된 행이 하나도
    없으면(=아직 관리자가 설정한 적 없음) None을 반환합니다 — 호출부에서 None은
    "전부 허용"으로 해석해야 합니다(신규 기능 도입으로 기존 팀이 갑자기 화면을
    못 보게 되는 일이 없도록 하는 기본값)."""
    conn = _get_conn()
    rows = conn.execute("SELECT section FROM team_permissions WHERE team = ?", (team,)).fetchall()
    conn.close()
    if not rows:
        return None
    return {r[0] for r in rows}


def get_all_team_permissions():
    """{team: {section, ...}} — 설정 화면에서 현재 상태를 한 번에 그리는 용도.
    행이 없는 팀은 이 딕셔너리에 아예 안 나온다(= 전체 허용 상태)."""
    conn = _get_conn()
    rows = conn.execute("SELECT team, section FROM team_permissions").fetchall()
    conn.close()
    result = {}
    for team, section in rows:
        result.setdefault(team, set()).add(section)
    return result


def set_team_permissions(team, sections):
    """이 팀의 허용 section을 sections(set/list)로 통째로 교체합니다. sections가
    비어있으면(체크 아무것도 안 함) 그 팀은 아무 화면도 못 보게 되므로, "전체 허용"으로
    되돌리려면 set_team_permissions(team, None)을 호출해 행 자체를 지워야 합니다."""
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM team_permissions WHERE team = ?", (team,))
        if sections:
            conn.executemany(
                "INSERT INTO team_permissions (team, section) VALUES (?, ?)",
                [(team, s) for s in sections],
            )
    conn.close()


def get_user_permissions(user_id):
    """이 사람만의 개인 접근권한(팀 설정보다 우선). 행이 하나도 없으면(=개인 설정
    안 함) None을 반환합니다 — 호출부는 None이면 팀 설정을 그대로 따라야 합니다."""
    conn = _get_conn()
    rows = conn.execute("SELECT section FROM user_permissions WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    if not rows:
        return None
    return {r[0] for r in rows}


def get_all_user_permissions():
    """{user_id: {section, ...}} — 설정 화면에서 현재 상태를 한 번에 그리는 용도."""
    conn = _get_conn()
    rows = conn.execute("SELECT user_id, section FROM user_permissions").fetchall()
    conn.close()
    result = {}
    for user_id, section in rows:
        result.setdefault(user_id, set()).add(section)
    return result


def set_user_permissions(user_id, sections):
    """이 사람의 개인 접근권한을 sections로 통째로 교체합니다. sections가 비어있거나
    None이면 개인 설정을 지워서 다시 소속 팀 설정을 따르게 됩니다("팀 설정 따르기")."""
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
        if sections:
            conn.executemany(
                "INSERT INTO user_permissions (user_id, section) VALUES (?, ?)",
                [(user_id, s) for s in sections],
            )
    conn.close()


def username_taken(username):
    conn = _get_conn()
    row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row is not None


def delete_user(user_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.close()


def set_admin(user_id, is_admin):
    conn = _get_conn()
    with conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))
    conn.close()


def create_access_request(username, display_name, reason, team):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO access_requests (username, display_name, reason, team, status, requested_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (username, display_name, reason, team, _now()),
        )
    conn.close()


def list_requests(status=None):
    cols = "id, username, display_name, reason, status, requested_at, decided_at, team"
    conn = _get_conn()
    if status:
        rows = conn.execute(
            f"SELECT {cols} FROM access_requests WHERE status = ? ORDER BY requested_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {cols} FROM access_requests ORDER BY requested_at DESC"
        ).fetchall()
    conn.close()
    return rows


def generate_temp_password(length=10):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_user_directly(username, display_name, password=None, is_admin=False, team=None, email=None):
    """접근 요청 절차 없이 관리자가 바로 계정을 만듭니다(예: 미리 알고 있는 동료 계정 발급).
    아이디가 이미 있으면 None을 반환합니다."""
    if username_taken(username):
        return None
    final_password = password or generate_temp_password()
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, is_admin, created_at, team, email) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (username, generate_password_hash(final_password), display_name, 1 if is_admin else 0, _now(), team, email),
        )
    conn.close()
    return {"username": username, "password": final_password, "email": email}


def approve_request(request_id, password=None, email=None):
    """요청을 승인하고 실제 로그인 계정을 만듭니다. password를 안 주면 임시 비밀번호를 자동 생성해 반환합니다."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT username, display_name, team FROM access_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    username, display_name, team = row
    existing = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        conn.close()
        return {"error": "duplicate_username"}

    final_password = password or generate_temp_password()
    with conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, is_admin, created_at, team, email) "
            "VALUES (?, ?, ?, 0, ?, ?, ?)",
            (username, generate_password_hash(final_password), display_name, _now(), team, email),
        )
        conn.execute(
            "UPDATE access_requests SET status = 'approved', decided_at = ? WHERE id = ?",
            (_now(), request_id),
        )
    conn.close()
    return {"username": username, "password": final_password, "email": email, "team": team}


def reject_request(request_id):
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE access_requests SET status = 'rejected', decided_at = ? WHERE id = ?",
            (_now(), request_id),
        )
    conn.close()


# ---------------------------------------------------------------------------
# 비밀번호 찾기: 이메일 인증코드
# ---------------------------------------------------------------------------
def generate_reset_code():
    return "".join(secrets.choice(string.digits) for _ in range(6))


def create_password_reset_code(user_id, valid_minutes=10):
    """6자리 인증코드를 새로 발급합니다. 같은 계정의 이전 미사용 코드는 무효화합니다."""
    from datetime import timedelta

    code = generate_reset_code()
    now = datetime.now()
    expires_at = (now + timedelta(minutes=valid_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn()
    with conn:
        conn.execute(
            "UPDATE password_reset_codes SET used = 1 WHERE user_id = ? AND used = 0",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO password_reset_codes (user_id, code, created_at, expires_at, used) "
            "VALUES (?, ?, ?, ?, 0)",
            (user_id, code, _now(), expires_at),
        )
    conn.close()
    return code


def verify_reset_code(user_id, code):
    """유효한(미사용, 미만료) 인증코드인지 확인합니다."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, expires_at FROM password_reset_codes "
        "WHERE user_id = ? AND code = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (user_id, code),
    ).fetchone()
    conn.close()
    if not row:
        return False
    reset_id, expires_at = row
    if datetime.now() > datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S"):
        return False
    return True


def reset_password_with_code(user_id, code, new_password):
    """인증코드가 유효하면 비밀번호를 바꾸고 코드를 소진합니다. 성공 여부(bool)를 반환합니다."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, expires_at FROM password_reset_codes "
        "WHERE user_id = ? AND code = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (user_id, code),
    ).fetchone()
    if not row:
        conn.close()
        return False
    reset_id, expires_at = row
    if datetime.now() > datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S"):
        conn.close()
        return False
    with conn:
        conn.execute("UPDATE password_reset_codes SET used = 1 WHERE id = ?", (reset_id,))
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id),
        )
    conn.close()
    return True


# ── 단판공시 월별 모니터링 메일 ──────────────────────────────────

def list_danpan_mail_recipients():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, email, label FROM danpan_mail_recipients ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def add_danpan_mail_recipient(email, label=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO danpan_mail_recipients (email, label, created_at) VALUES (?, ?, ?)",
            (email, label, _now()),
        )
    conn.close()


def delete_danpan_mail_recipient(recipient_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM danpan_mail_recipients WHERE id = ?", (recipient_id,))
    conn.close()


def log_danpan_mail(year_month, recipient_count, site_count, triggered_by):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO danpan_mail_log (year_month, sent_at, recipient_count, site_count, triggered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (year_month, _now(), recipient_count, site_count, triggered_by),
        )
    conn.close()


def get_last_danpan_mail():
    """가장 최근 발송 기록 1건(없으면 None) — (year_month, sent_at, recipient_count, site_count, triggered_by)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT year_month, sent_at, recipient_count, site_count, triggered_by "
        "FROM danpan_mail_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def was_danpan_mail_sent_for(year_month):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM danpan_mail_log WHERE year_month = ? LIMIT 1", (year_month,)
    ).fetchone()
    conn.close()
    return row is not None


# ── 단판공시 메일링 전담(부분 관리자) 권한 ──────────────────────

def is_danpan_mail_admin(user_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM danpan_mail_admins WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


def grant_danpan_mail_admin(user_id):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO danpan_mail_admins (user_id, granted_at) VALUES (?, ?)",
            (user_id, _now()),
        )
    conn.close()


def revoke_danpan_mail_admin(user_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM danpan_mail_admins WHERE user_id = ?", (user_id,))
    conn.close()


def list_danpan_mail_admin_ids():
    conn = _get_conn()
    rows = conn.execute("SELECT user_id FROM danpan_mail_admins").fetchall()
    conn.close()
    return {r[0] for r in rows}


# ── 자금계획(3개월 자금수지) 월별 요청 메일 ──────────────────────

def list_cashflow_plan_mail_recipients():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, email, label FROM cashflow_plan_mail_recipients ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def add_cashflow_plan_mail_recipient(email, label=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO cashflow_plan_mail_recipients (email, label, created_at) VALUES (?, ?, ?)",
            (email, label, _now()),
        )
    conn.close()


def delete_cashflow_plan_mail_recipient(recipient_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM cashflow_plan_mail_recipients WHERE id = ?", (recipient_id,))
    conn.close()


def log_cashflow_plan_mail(year_month, recipient_count, triggered_by):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO cashflow_plan_mail_log (year_month, sent_at, recipient_count, triggered_by) "
            "VALUES (?, ?, ?, ?)",
            (year_month, _now(), recipient_count, triggered_by),
        )
    conn.close()


def get_last_cashflow_plan_mail():
    """가장 최근 발송 기록 1건(없으면 None) — (year_month, sent_at, recipient_count, triggered_by)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT year_month, sent_at, recipient_count, triggered_by "
        "FROM cashflow_plan_mail_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def was_cashflow_plan_mail_sent_for(year_month):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM cashflow_plan_mail_log WHERE year_month = ? LIMIT 1", (year_month,)
    ).fetchone()
    conn.close()
    return row is not None


# ── 자금계획 메일링 전담(부분 관리자) 권한 ────────────────────────

def is_cashflow_plan_mail_admin(user_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM cashflow_plan_mail_admins WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


def grant_cashflow_plan_mail_admin(user_id):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO cashflow_plan_mail_admins (user_id, granted_at) VALUES (?, ?)",
            (user_id, _now()),
        )
    conn.close()


def revoke_cashflow_plan_mail_admin(user_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM cashflow_plan_mail_admins WHERE user_id = ?", (user_id,))
    conn.close()


def list_cashflow_plan_mail_admin_ids():
    conn = _get_conn()
    rows = conn.execute("SELECT user_id FROM cashflow_plan_mail_admins").fetchall()
    conn.close()
    return {r[0] for r in rows}


# ── 자금계획 서식 파일(레미콘·건자재·동양공통 / 플랜트 / 건설) ────

CASHFLOW_PLAN_TEMPLATE_SLOTS = [
    ("remicon_common", "레미콘ㆍ건자재ㆍ(주)동양공통"),
    ("plant", "플랜트"),
    ("construction", "건설"),
]


def save_cashflow_plan_template(slot, filename, file_bytes, uploaded_by=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO cashflow_plan_templates (slot, filename, file_blob, uploaded_by, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(slot) DO UPDATE SET filename=excluded.filename, file_blob=excluded.file_blob, "
            "uploaded_by=excluded.uploaded_by, uploaded_at=excluded.uploaded_at",
            (slot, filename, file_bytes, uploaded_by, _now()),
        )
    conn.close()


def list_cashflow_plan_templates():
    """등록된 서식 메타데이터만(파일 본문 제외) — {slot: {filename, uploaded_by, uploaded_at}}."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT slot, filename, uploaded_by, uploaded_at FROM cashflow_plan_templates"
    ).fetchall()
    conn.close()
    return {r[0]: {"filename": r[1], "uploaded_by": r[2], "uploaded_at": r[3]} for r in rows}


def get_cashflow_plan_template_file(slot):
    """(파일명, bytes) 반환 — 없으면 None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT filename, file_blob FROM cashflow_plan_templates WHERE slot = ?", (slot,)
    ).fetchone()
    conn.close()
    return (row[0], row[1]) if row else None


# ── 공정위 공시대상기업집단 대규모내부거래(상품ㆍ용역거래) 취합요청 협조전 ──
# cashflow_plan_* 과 완전히 같은 구조 — 함수 이름만 ftc_disclosure로 바꿔 그대로 복제.

def list_ftc_disclosure_mail_recipients():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, email, label FROM ftc_disclosure_mail_recipients ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def add_ftc_disclosure_mail_recipient(email, label=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO ftc_disclosure_mail_recipients (email, label, created_at) VALUES (?, ?, ?)",
            (email, label, _now()),
        )
    conn.close()


def delete_ftc_disclosure_mail_recipient(recipient_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM ftc_disclosure_mail_recipients WHERE id = ?", (recipient_id,))
    conn.close()


def log_ftc_disclosure_mail(period_label, recipient_count, triggered_by):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO ftc_disclosure_mail_log (period_label, sent_at, recipient_count, triggered_by) "
            "VALUES (?, ?, ?, ?)",
            (period_label, _now(), recipient_count, triggered_by),
        )
    conn.close()


def get_last_ftc_disclosure_mail():
    """가장 최근 발송 기록 1건(없으면 None) — (period_label, sent_at, recipient_count, triggered_by)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT period_label, sent_at, recipient_count, triggered_by "
        "FROM ftc_disclosure_mail_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row


def was_ftc_disclosure_mail_sent_for(period_label):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM ftc_disclosure_mail_log WHERE period_label = ? LIMIT 1", (period_label,)
    ).fetchone()
    conn.close()
    return row is not None


# ── 공정위 공시 협조전 전담(부분 관리자) 권한 ────────────────────────

def is_ftc_disclosure_mail_admin(user_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM ftc_disclosure_mail_admins WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None


def grant_ftc_disclosure_mail_admin(user_id):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO ftc_disclosure_mail_admins (user_id, granted_at) VALUES (?, ?)",
            (user_id, _now()),
        )
    conn.close()


def revoke_ftc_disclosure_mail_admin(user_id):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM ftc_disclosure_mail_admins WHERE user_id = ?", (user_id,))
    conn.close()


def list_ftc_disclosure_mail_admin_ids():
    conn = _get_conn()
    rows = conn.execute("SELECT user_id FROM ftc_disclosure_mail_admins").fetchall()
    conn.close()
    return {r[0] for r in rows}


# ── 공정위 공시 첨부 서식(내부거래 추정 집계 / 동일인 등 출자계열회사 리스트) ──

FTC_DISCLOSURE_TEMPLATE_SLOTS = [
    ("trade_summary", "내부거래 추정 집계"),
    ("affiliate_list", "동일인 등 출자계열회사 리스트"),
]


def save_ftc_disclosure_template(slot, filename, file_bytes, uploaded_by=None):
    conn = _get_conn()
    with conn:
        conn.execute(
            "INSERT INTO ftc_disclosure_templates (slot, filename, file_blob, uploaded_by, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(slot) DO UPDATE SET filename=excluded.filename, file_blob=excluded.file_blob, "
            "uploaded_by=excluded.uploaded_by, uploaded_at=excluded.uploaded_at",
            (slot, filename, file_bytes, uploaded_by, _now()),
        )
    conn.close()


def list_ftc_disclosure_templates():
    """등록된 서식 메타데이터만(파일 본문 제외) — {slot: {filename, uploaded_by, uploaded_at}}."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT slot, filename, uploaded_by, uploaded_at FROM ftc_disclosure_templates"
    ).fetchall()
    conn.close()
    return {r[0]: {"filename": r[1], "uploaded_by": r[2], "uploaded_at": r[3]} for r in rows}


def get_ftc_disclosure_template_file(slot):
    """(파일명, bytes) 반환 — 없으면 None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT filename, file_blob FROM ftc_disclosure_templates WHERE slot = ?", (slot,)
    ).fetchone()
    conn.close()
    return (row[0], row[1]) if row else None
