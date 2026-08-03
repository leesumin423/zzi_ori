# -*- coding: utf-8 -*-
"""(주)동양 통합 자금포털 — 허브(hub) 앱.

각 화면(주가/공시, 자금(차입), 퇴직연금)은 이미 따로 만들어져 각자의 포트로 돌아가는
독립 프로그램입니다. 이 허브는 그 프로그램들을 직접 다시 만들지 않고,
① 로그인/접근승인 ② 탭 메뉴 ③ 각 프로그램을 iframe으로 보여주는 역할만 합니다.

실행 전 준비: 아래 3개 프로그램이 먼저(또는 이 허브와 함께) 켜져 있어야 합니다.
- 주가현황/공시: ai 개발관련/주가현황/주가현황_실행하기.bat (포트 5000)
- 자금(차입금관리): ai 개발관련/차입금관리/프로그램_실행하기.bat (포트 8501)
- 퇴직연금: 퇴직연금_보고시스템/run_dashboard.py (포트 8000)
"""
import sys
import threading
import time as _time_module
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response

import hub_config
import hub_db
import mailer
import danpan_mail
import danpan_tracking_db
import cashflow_plan_mail
import ftc_disclosure_mail

# 차입금관리 폴더의 report_shared.py(엑셀 시트 렌더링)와 monthly_report_db.py(월간보고서
# 저장소)를 그대로 재사용한다 — 같은 로직을 통합포털에 새로 베껴 쓰면 나중에 둘이
# 어긋날 수 있어서, 폴더 경로만 sys.path에 추가해 원본 모듈을 그대로 import한다.
sys.path.insert(0, hub_config.TREASURY_APP_DIR)
import report_shared
import monthly_report_db as report_db

app = Flask(__name__)
app.secret_key = hub_config.SECRET_KEY

# 퇴직연금 iframe URL에 붙이는 캐시버스터 — 그 앱의 index.html/style.css/app.js를
# 고칠 때마다 이 값을 올려주면(예: 날짜 문자열) 브라우저가 예전 index.html을
# 계속 캐시해서 통합포털에서 새 화면이 안 보이는 문제를 막을 수 있다.
PENSION_ASSET_VERSION = '20260803e'

# 대여/운용은 단일 시트·단순 표라 화면에서 직접 조회+수정(editable=True)이 가능하고,
# 자금수지(표지 포함)·어음현황·전체(표지부터 전체출력)는 다단 헤더/대량 병합셀에 시트도
# 여러 장(sheets)이라 화면 조회 전용(editable=False)으로 두고 데이터 등록/교체는 관리
# 탭의 업로드로만 한다(차입금관리 Streamlit 쪽과 동일한 범위 — report_shared.render_sheet_html
# 을 그대로 재사용). '월간보고서' 탭 하위 서브내비(대여/운용/차입/자금수지/어음현황)는
# finance_view.html이 그린다 — REPORT_SUBNAV 순서가 그 서브탭 순서다. '차입'(차입금 및
# 담보현황)은 원래 차입금관리(Streamlit) 안에 따로 있던 '📑 월간보고서' 메뉴에 있었는데,
# 그 메뉴는 이제 지우고 이 탭 하나로 합쳤다(중복 방지).
FINANCE_CATEGORIES = {
    'lend': {'label': '대여', 'sheet': '대여금 현황', 'editable': True},
    'invest': {'label': '운용', 'sheet': '자금운용현황', 'editable': True},
    'borrow': {'label': '차입', 'sheet': '차입금 및 담보현황', 'editable': True},
    'manage': {
        'label': '자금수지',
        # 대여ㆍ운용ㆍ어음현황 서브탭에는 '표지'가 안 나오는데 자금수지만 나와서
        # 통일감이 없다는 피드백에 따라 '표지'는 빼고 '자금현황'부터 바로 보여준다
        # ('전체(표지부터)'는 이름 그대로 표지 포함 전체 출력이라 그대로 둔다).
        'sheets': [
            '자금현황(통합 누적-보고용)', '자금현황(통합 누적-보고용) (2)',
            '사업본부 통합', '건재', '건설', '플랜트', '공통',
        ],
        'editable': False,
    },
    'other': {
        'label': '어음현황',
        'sheets': ['어음현황', '어음현황 (2)'],
        'editable': False,
    },
    'all': {
        'label': '전체(표지부터)',
        'sheets': [
            '표지',
            '자금현황(통합 누적-보고용)', '자금현황(통합 누적-보고용) (2)',
            '사업본부 통합', '건재', '건설', '플랜트', '공통',
            '대여금 현황',
            '자금운용현황',
            '차입금 및 담보현황',
            '어음현황', '어음현황 (2)',
        ],
        'editable': False,
    },
}

# 월간보고서 탭 안의 서브내비(finance_view.html 상단 pill) 순서 — '전체'는 인쇄용
# 별도 링크로 두고 pill에는 안 넣는다.
REPORT_SUBNAV = ['lend', 'invest', 'borrow', 'manage', 'other']

# 허브 최상단 4개 대분류 — 팀별 접근권한(hub_db.team_permissions)의 단위와 정확히
# 같다(자금 하위의 차입/월간보고서/관리는 따로 안 나눔). portal()의 tabs 순서도
# 항상 이 순서를 따른다.
HUB_SECTIONS = [
    {'id': 'stock', 'label': '📈 주가'},
    {'id': 'disclosure', 'label': '📋 공시'},
    {'id': 'treasury', 'label': '💰 자금'},
    {'id': 'pension', 'label': '🧓 퇴직연금'},
]


def _select_report_row(report_id=None):
    """등록된 월간보고서 목록과, 그중 조회할 한 건을 함께 반환한다. report_id가 없거나
    목록에 없으면(잘못된 값 등) 최신 월을 기본값으로 쓴다 — 뷰 화면의 월 선택 드롭다운이
    이 함수로 '조회할 월'과 '드롭다운에 채울 전체 목록'을 한 번에 얻는다."""
    rows = report_db.list_reports()
    if not rows:
        return None, []
    if report_id is not None:
        match = next((r for r in rows if r[0] == report_id), None)
        if match:
            return match, rows
    return rows[0], rows


def _parse_report_id_arg():
    raw = request.args.get('report_id')
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# 공정거래법 제26조/시행령 제33조 판단 로직(check_ftc_disclosure)은 report_shared.py에
# 있고(주가현황/server.py의 공시 탭과 동일 기준), (주)동양의 자본총계·자본금은 이미
# 그 서버가 DART에서 조회해두고 있으므로 그 값을 그대로 가져다 쓴다(중복 조회/구현 없이).
DONGYANG_CAPITAL_CACHE = {"value": None, "ts": 0}
DONGYANG_CAPITAL_TTL_SECONDS = 3600


def _get_dongyang_capital_base():
    """주가현황 서버(공시 탭)가 이미 조회해둔 (주)동양 자본총계·자본금 중 큰 값을 가져온다.
    실패하면 None을 반환(호출부에서 '100억원 기준만 확인' 식으로 처리)."""
    import time
    now = time.time()
    if DONGYANG_CAPITAL_CACHE["value"] is not None and now - DONGYANG_CAPITAL_CACHE["ts"] < DONGYANG_CAPITAL_TTL_SECONDS:
        return DONGYANG_CAPITAL_CACHE["value"]
    try:
        host = request.host.split(':')[0]
    except RuntimeError:
        host = 'localhost'  # 요청 컨텍스트 밖(테스트 등)에서는 로컬로 폴백
    try:
        resp = requests.get(
            f"http://{host}:{hub_config.PORT_STOCK_DISCLOSURE}/data",
            params={"section": "subsidiary_capital"}, timeout=8,
        )
        resp.raise_for_status()
        records = resp.json().get('records', [])
        dongyang = next((r for r in records if r.get('name') == '동양(주)'), None)
        capital_base = dongyang.get('capital_base') if dongyang else None
        if capital_base:
            DONGYANG_CAPITAL_CACHE.update(value=capital_base, ts=now)
        return capital_base
    except Exception as e:
        print(f"[DEBUG] (주)동양 자본총계 조회 실패(주가현황 서버 미기동 등): {e}")
        return None


def _compute_lend_ftc_review(ws):
    """대여금 현황 시트에서 거래선별 증가액(같은 이름의 열이 여러 개면 합산)을 계산해,
    check_ftc_disclosure(공정거래법 제26조 기준)로 공시대상 여부를 판단한다.
    기말 잔액은 판단에 쓰지 않는다(요청사항) — 증가액만 확인."""
    header_row = None
    for r in range(1, min(ws.max_row, 15) + 1):
        if any(ws.cell(row=r, column=c).value == '거래선' for c in range(1, ws.max_column + 1)):
            header_row = r
            break
    if header_row is None:
        return []

    col_map = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        if v:
            col_map.setdefault(str(v).strip(), []).append(c)

    counterparty_cols = col_map.get('거래선', [])
    increase_cols = col_map.get('증가액', [])
    if not counterparty_cols or not increase_cols:
        return []
    counterparty_col = counterparty_cols[0]

    capital_base = _get_dongyang_capital_base()

    results = []
    for r in range(header_row + 1, ws.max_row + 1):
        name = ws.cell(row=r, column=counterparty_col).value
        if not name:
            continue
        total_increase = 0
        for c in increase_cols:
            v = ws.cell(row=r, column=c).value
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                total_increase += v
        if total_increase <= 0:
            continue
        check = report_shared.check_ftc_disclosure('fund_securities_asset', total_increase, capital_base)
        if check and check['is_disclosure_required']:
            results.append({"name": str(name), "increase": total_increase, "reason": check['reason']})
    return results, capital_base


def _normalize_company_name_for_affiliate_match(name: str) -> str:
    """"OO(주)"(접미)ㆍ"(주)OO"(접두)ㆍ"OO㈜"ㆍ"OO 주식회사"ㆍ그리고 아무 표기도
    없는 "OO"까지, 표기 위치·유무와 무관하게 비교할 수 있도록 상호 표시를 아예
    다 떼어낸 "알맹이 이름"으로 정규화한다. 실제로 대여금 시트의 거래선은
    "유진홈센터"처럼 "(주)"를 아예 안 붙여서 나오는데, 공시 탭의 계열사 목록에는
    "유진홈센터(주)"로 나와서 — 표기를 접미사로만 통일하는 규칙으로는 이 둘이
    같은 회사로 안 잡혔다(실제로 겪은 오탐)."""
    name = (name or '').strip().replace('㈜', '(주)').replace('(주)', '')
    if name.startswith('주식회사'):
        name = name[4:]
    elif name.endswith('주식회사'):
        name = name[:-4]
    return name.strip()


_group_affiliate_names_cache = {"ts": 0.0, "names": None}
GROUP_AFFILIATE_CACHE_TTL_SECONDS = 3600


def _get_group_affiliate_names():
    """(주)동양이 속한 기업집단 소속 회사 전체의 정규화된 이름 집합을 반환한다.
    주가현황 서버(공시 탭)가 이미 DART "기업집단현황공시"에서 조회해둔 약 70개사
    목록(subsidiary_capital)을 그대로 가져다 쓴다 — 대여금 거래선이 이 안에 있으면
    계열사, 없으면 비계열사로 본다."""
    now = _time_module.time()
    if _group_affiliate_names_cache["names"] is not None and now - _group_affiliate_names_cache["ts"] < GROUP_AFFILIATE_CACHE_TTL_SECONDS:
        return _group_affiliate_names_cache["names"]
    try:
        host = request.host.split(':')[0]
    except RuntimeError:
        host = 'localhost'
    try:
        resp = requests.get(
            f"http://{host}:{hub_config.PORT_STOCK_DISCLOSURE}/data",
            params={"section": "subsidiary_capital"}, timeout=8,
        )
        resp.raise_for_status()
        records = resp.json().get('records', [])
        names = {_normalize_company_name_for_affiliate_match(r['name']) for r in records if r.get('name')}
        _group_affiliate_names_cache.update(ts=now, names=names)
        return names
    except Exception as e:
        print(f"[DEBUG] 계열사 목록 조회 실패(주가현황 서버 미기동 등): {e}")
        return set()


def _compute_lend_affiliate_summary(ws):
    """대여금 현황 시트에서 거래선별 '기말 대여금'을 계열사ㆍ비계열사로 나눠
    합산한다. 계열사 여부는 공시 탭이 이미 조회해둔 기업집단 소속회사 전체
    목록(_get_group_affiliate_names)과 대조해서 판단한다."""
    header_row = None
    for r in range(1, min(ws.max_row, 15) + 1):
        if any(ws.cell(row=r, column=c).value == '거래선' for c in range(1, ws.max_column + 1)):
            header_row = r
            break
    if header_row is None:
        return None

    counterparty_col = None
    ending_col = None
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        if not v:
            continue
        text = str(v).strip()
        if text == '거래선' and counterparty_col is None:
            counterparty_col = c
        # "기말 대여금\n(2026.06.30)"처럼 기준일이 매달 바뀌어 뒤에 붙으므로
        # 정확히 일치가 아니라 "기말"로 시작하는지로 찾는다.
        if text.startswith('기말') and ending_col is None:
            ending_col = c
    if counterparty_col is None or ending_col is None:
        return None

    affiliate_names = _get_group_affiliate_names()
    if not affiliate_names:
        return None

    affiliate_total = 0
    non_affiliate_total = 0
    for r in range(header_row + 1, ws.max_row + 1):
        name = ws.cell(row=r, column=counterparty_col).value
        if not name:
            continue
        v = ws.cell(row=r, column=ending_col).value
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        norm = _normalize_company_name_for_affiliate_match(str(name))
        if norm in affiliate_names:
            affiliate_total += v
        else:
            non_affiliate_total += v

    return {"affiliate_total": affiliate_total, "non_affiliate_total": non_affiliate_total}

hub_db.ensure_bootstrap_admin(hub_config.BOOTSTRAP_ADMIN_USERNAME, hub_config.BOOTSTRAP_ADMIN_PASSWORD)


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return hub_db.get_user_by_id(uid)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for('login', next=request.path))
        if not user['is_admin']:
            flash('관리자만 접근할 수 있는 화면입니다.', 'error')
            return redirect(url_for('portal'))
        return view(*args, **kwargs)
    return wrapped


def danpan_mail_access_required(view):
    """단판공시 메일링 설정만은 전체 관리자가 아니어도(예: 공시 담당자) 열어줄 수 있게
    admin_required와 별도로 둔 게이트 — 전체 관리자는 항상 통과하고, 그 외엔
    danpan_mail_admins에 등록된 사람만 통과한다(계정 승인 등 나머지 관리자 화면은 못 봄)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for('login', next=request.path))
        if not user['is_admin'] and not hub_db.is_danpan_mail_admin(user['id']):
            flash('단판공시 메일링 설정 권한이 없습니다.', 'error')
            return redirect(url_for('portal'))
        return view(*args, **kwargs)
    return wrapped


def cashflow_plan_mail_access_required(view):
    """자금계획(3개월 자금수지) 메일링 설정만은 전체 관리자가 아니어도(예: 자금팀
    담당자) 열어줄 수 있게 danpan_mail_access_required와 같은 방식으로 둔 게이트."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for('login', next=request.path))
        if not user['is_admin'] and not hub_db.is_cashflow_plan_mail_admin(user['id']):
            flash('자금계획 메일링 설정 권한이 없습니다.', 'error')
            return redirect(url_for('portal'))
        return view(*args, **kwargs)
    return wrapped


def ftc_disclosure_mail_access_required(view):
    """공정위 공시(대규모내부거래) 협조전 설정도 cashflow_plan_mail_access_required와
    같은 방식으로, 전체 관리자가 아닌 담당자에게 별도로 권한을 부여할 수 있게 한다."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for('login', next=request.path))
        if not user['is_admin'] and not hub_db.is_ftc_disclosure_mail_admin(user['id']):
            flash('공정위 공시 협조전 설정 권한이 없습니다.', 'error')
            return redirect(url_for('portal'))
        return view(*args, **kwargs)
    return wrapped


@app.route('/')
def index():
    if current_user():
        return redirect(url_for('portal'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = hub_db.verify_login(username, password)
        if user:
            session['user_id'] = user['id']
            return redirect(request.args.get('next') or url_for('portal'))
        flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/request-access', methods=['GET', 'POST'])
def request_access():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        team = request.form.get('team', '').strip()
        reason = request.form.get('reason', '').strip()
        if not username or not display_name or not team:
            flash('아이디, 이름, 팀명은 필수입니다.', 'error')
        elif hub_db.username_taken(username):
            flash('이미 사용 중인 아이디입니다. 다른 아이디를 입력해주세요.', 'error')
        else:
            hub_db.create_access_request(username, display_name, reason, team)
            flash(
                f'접근 요청이 접수되었습니다. 승인되면 {mailer.email_for_username(username)} 메일로 '
                '초기 비밀번호가 발송됩니다.',
                'success',
            )
            return redirect(url_for('login'))
    return render_template('request_access.html', email_domain=hub_config.EMAIL_DOMAIN)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        user = hub_db.get_user_by_username(username)
        if user:
            code = hub_db.create_password_reset_code(user['id'])
            to_email = user['email'] or mailer.email_for_username(username)
            mail_result = mailer.send_mail(
                to_email,
                '[통합 자금포털] 비밀번호 재설정 인증코드',
                f"{user['display_name'] or username}님,\n\n비밀번호 재설정 인증코드는 [{code}] 입니다. "
                "10분 이내에 입력해주세요.",
            )
            session['reset_user_id'] = user['id']
            session['reset_username'] = username
            if mail_result['test_mode']:
                session['reset_test_code'] = code
                session['reset_test_email'] = to_email
            flash(f'{to_email} (으)로 인증코드를 보냈습니다.', 'info')
        else:
            flash('등록된 아이디가 아닙니다.', 'error')
            return render_template('forgot_password.html')
        return redirect(url_for('reset_password'))
    return render_template('forgot_password.html')


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    user_id = session.get('reset_user_id')
    if not user_id:
        flash('먼저 아이디를 입력해 인증코드를 받아주세요.', 'error')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not code or not new_password:
            flash('인증코드와 새 비밀번호를 모두 입력해주세요.', 'error')
        elif new_password != confirm_password:
            flash('새 비밀번호가 서로 일치하지 않습니다.', 'error')
        elif len(new_password) < 4:
            flash('비밀번호는 4자 이상으로 설정해주세요.', 'error')
        elif hub_db.reset_password_with_code(user_id, code, new_password):
            session.pop('reset_user_id', None)
            session.pop('reset_username', None)
            session.pop('reset_test_code', None)
            session.pop('reset_test_email', None)
            flash('비밀번호가 재설정되었습니다. 새 비밀번호로 로그인해주세요.', 'success')
            return redirect(url_for('login'))
        else:
            flash('인증코드가 올바르지 않거나 만료되었습니다. 다시 요청해주세요.', 'error')

    return render_template(
        'reset_password.html',
        username=session.get('reset_username'),
        test_code=session.get('reset_test_code'),
        test_email=session.get('reset_test_email'),
    )


@app.route('/portal')
@login_required
def portal():
    user = current_user()
    # 이 허브에 접속한 주소(호스트명)를 그대로 재사용해 각 서비스의 iframe 주소를 만든다.
    # (localhost로 고정하면 다른 PC에서 접속했을 때 그 PC 자신을 가리켜버려서 깨진다.)
    host = request.host.split(':')[0]
    # 접근권한 우선순위: 관리자(항상 전체) > 개인별 설정(임원ㆍ팀장 등 예외) > 팀 설정
    # > 아무것도 설정 안 함(전체 허용, 기본값). allowed_sections가 None이면 "전체 허용"
    # — 아래서 tabs를 다 만든 뒤 이 값으로 걸러낸다(HUB_SECTIONS 순서와 tabs 순서는 항상 같다).
    if user['is_admin']:
        allowed_sections = None
    else:
        allowed_sections = hub_db.get_user_permissions(user['id'])
        if allowed_sections is None:
            allowed_sections = hub_db.get_team_permissions(user['team'])
    # 'iframe' 탭은 다른 프로그램 화면을 그대로 보여준다. 자금 하위 구성:
    # 차입(실시간 관리 대시보드) / 월간보고서(대여·운용·자금수지·어음현황을 그 안의
    # 서브내비로 넘나드는 뷰 시트 — finance_view.html 참고) / 자금관리(자금계획
    # 협조전 담당자 전용 — 실제 "보내기"는 여기서만 하고, 관리자 화면은 수신자ㆍ
    # 서식ㆍ담당자 지정 같은 "설정"만 한다) / 관리(관리자 전용, 데이터 등록·수정·출력).
    treasury_children = [
        {
            'id': 'treasury-borrow', 'label': '차입', 'type': 'iframe',
            'url': f'http://{host}:{hub_config.PORT_TREASURY}/',
        },
        {
            'id': 'treasury-report', 'label': '월간보고서', 'type': 'iframe',
            'url': url_for('finance_view', category='lend'),
        },
    ]
    if user['is_admin'] or hub_db.is_cashflow_plan_mail_admin(user['id']):
        treasury_children.append({
            'id': 'treasury-cashflow-send', 'label': '📝 자금관리', 'type': 'iframe',
            'url': url_for('finance_cashflow_send'),
        })
    if user['is_admin']:
        treasury_children.append({
            'id': 'treasury-admin', 'label': '⚙️ 관리', 'type': 'iframe',
            'url': url_for('finance_admin'),
        })

    tabs = [
        {
            'id': 'stock',
            'label': '📈 주가',
            'type': 'iframe',
            'url': f'http://{host}:{hub_config.PORT_STOCK_DISCLOSURE}/주가현황.html',
        },
        {
            'id': 'disclosure',
            'label': '📋 공시',
            'type': 'iframe',
            'url': f'http://{host}:{hub_config.PORT_STOCK_DISCLOSURE}/주가현황.html?page=disclosures',
        },
        {
            'id': 'treasury',
            'label': '💰 자금',
            'type': 'group',
            'children': treasury_children,
        },
        {
            'id': 'pension',
            'label': '🧓 퇴직연금',
            'type': 'iframe',
            # 퇴직연금 앱의 index.html 자체를 브라우저가 오래 캐시해서, 그 안의
            # style.css/app.js 버전을 올려도 iframe이 예전 index.html을 계속
            # 재사용해 반영이 안 되는 문제가 있었다 — iframe src에 버전 쿼리를
            # 붙여 이 앱을 고칠 때마다(PENSION_ASSET_VERSION만 올리면) 강제로
            # 새로 받아오게 한다.
            'url': f'http://{host}:{hub_config.PORT_PENSION}/?_v={PENSION_ASSET_VERSION}',
        },
    ]
    if allowed_sections is not None:
        tabs = [t for t in tabs if t['id'] in allowed_sections]
    can_manage_danpan_mail = bool(user['is_admin']) or hub_db.is_danpan_mail_admin(user['id'])
    can_manage_cashflow_mail = bool(user['is_admin']) or hub_db.is_cashflow_plan_mail_admin(user['id'])
    return render_template(
        'portal.html', user=user, tabs=tabs,
        can_manage_danpan_mail=can_manage_danpan_mail,
        can_manage_cashflow_mail=can_manage_cashflow_mail,
    )


@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    user = current_user()
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not hub_db.verify_password(user['id'], current_password):
            flash('현재 비밀번호가 올바르지 않습니다.', 'error')
        elif not new_password or new_password != confirm_password:
            flash('새 비밀번호가 서로 일치하지 않습니다.', 'error')
        elif len(new_password) < 4:
            flash('비밀번호는 4자 이상으로 설정해주세요.', 'error')
        else:
            hub_db.change_password(user['id'], new_password)
            flash('비밀번호를 변경했습니다.', 'success')
            return redirect(url_for('account'))
    # 메일 항목이 아직 비어있으면(과거 계정 등) 그룹웨어 규칙(아이디@도메인)으로
    # 자동 채워서 보여준다 — 메일링 발송 시 이 값을 그대로 쓰므로 비워두지 않도록 유도.
    default_email = user['email'] or mailer.email_for_username(user['username'])
    return render_template('account.html', user=user, default_email=default_email)


@app.route('/account/profile', methods=['POST'])
@login_required
def account_profile():
    user = current_user()
    team = request.form.get('team', '').strip()
    email = request.form.get('email', '').strip()
    if not team:
        flash('팀은 비워둘 수 없습니다 — 추후 팀별 화면 접근 권한 분리의 기준이 됩니다.', 'error')
    elif not email:
        flash('메일 주소는 비워둘 수 없습니다 — 메일링(계정 발급/비밀번호 재설정 등)에 사용됩니다.', 'error')
    else:
        hub_db.update_profile(user['id'], team, email)
        flash('내 정보를 수정했습니다.', 'success')
    return redirect(url_for('account'))


@app.route('/admin')
@admin_required
def admin():
    pending = hub_db.list_requests(status='pending')
    decided = [r for r in hub_db.list_requests() if r[4] != 'pending']
    users = hub_db.list_users()
    new_credential = session.pop('new_credential', None)
    new_credential_mail = session.pop('new_credential_mail', None)
    return render_template(
        'admin.html', pending=pending, decided=decided, users=users,
        new_credential=new_credential, new_credential_mail=new_credential_mail,
    )


@app.route('/admin/team-access')
@admin_required
def admin_team_access():
    teams = hub_db.list_distinct_teams()
    current = hub_db.get_all_team_permissions()  # {team: {section_id, ...}}; 없는 팀=전체허용
    return render_template(
        'team_access.html', teams=teams, sections=HUB_SECTIONS, current=current,
    )


@app.route('/admin/team-access/save', methods=['POST'])
@admin_required
def admin_team_access_save():
    team = request.form.get('team', '').strip()
    if not team:
        flash('팀을 확인할 수 없습니다.', 'error')
        return redirect(url_for('admin_team_access'))
    mode = request.form.get('mode', 'restricted')
    if mode == 'all':
        # "전체 허용"으로 되돌리기 — 행을 아예 지워서 '설정 안 함' 상태로 만든다.
        hub_db.set_team_permissions(team, None)
        flash(f'{team} 팀을 전체 허용으로 되돌렸습니다.', 'success')
    else:
        selected = request.form.getlist('sections')
        valid_ids = {s['id'] for s in HUB_SECTIONS}
        selected = [s for s in selected if s in valid_ids]
        hub_db.set_team_permissions(team, selected)
        if selected:
            flash(f'{team} 팀 접근권한을 저장했습니다.', 'success')
        else:
            flash(f'{team} 팀은 선택된 화면이 없어 모든 화면이 보이지 않게 됩니다 — 의도한 게 맞는지 확인해주세요.', 'error')
    return redirect(url_for('admin_team_access'))


@app.route('/admin/user-access')
@admin_required
def admin_user_access():
    """개인별 접근권한 — 임원ㆍ팀장처럼 소속 팀 설정과 무관하게 이 사람만 예외로
    열어줘야 하는 경우. 팀 설정보다 우선 적용된다(portal()에서 확인)."""
    # 관리자 계정은 이 설정과 무관하게 항상 전체 화면을 보므로(portal() 참고) 목록에서 뺀다.
    users = [u for u in hub_db.list_users() if not u[3]]
    current = hub_db.get_all_user_permissions()  # {user_id: {section_id, ...}}; 없으면 팀 설정을 따름
    team_current = hub_db.get_all_team_permissions()
    return render_template(
        'user_access.html', users=users, sections=HUB_SECTIONS,
        current=current, team_current=team_current,
    )


@app.route('/admin/user-access/save', methods=['POST'])
@admin_required
def admin_user_access_save():
    try:
        user_id = int(request.form.get('user_id', ''))
    except (TypeError, ValueError):
        flash('사용자를 확인할 수 없습니다.', 'error')
        return redirect(url_for('admin_user_access'))
    target = hub_db.get_user_by_id(user_id)
    if not target:
        flash('사용자를 찾을 수 없습니다.', 'error')
        return redirect(url_for('admin_user_access'))

    mode = request.form.get('mode', 'restricted')
    if mode == 'follow_team':
        # 개인 설정을 지워서 다시 소속 팀 설정을 따르게 한다.
        hub_db.set_user_permissions(user_id, None)
        flash(f"{target['display_name'] or target['username']}님을 팀 설정을 따르도록 되돌렸습니다.", 'success')
    else:
        selected = request.form.getlist('sections')
        valid_ids = {s['id'] for s in HUB_SECTIONS}
        selected = [s for s in selected if s in valid_ids]
        hub_db.set_user_permissions(user_id, selected)
        if selected:
            flash(f"{target['display_name'] or target['username']}님의 개인 접근권한을 저장했습니다(팀 설정보다 우선 적용됩니다).", 'success')
        else:
            flash(f"{target['display_name'] or target['username']}님은 선택된 화면이 없어 모든 화면이 보이지 않게 됩니다 — 의도한 게 맞는지 확인해주세요.", 'error')
    return redirect(url_for('admin_user_access'))


@app.route('/admin/danpan-mail')
@danpan_mail_access_required
def admin_danpan_mail():
    recipients = hub_db.list_danpan_mail_recipients()
    last_sent = hub_db.get_last_danpan_mail()

    sites, sites_error = [], None
    try:
        host = request.host.split(':')[0]
        resp = requests.get(
            f"http://{host}:{hub_config.PORT_STOCK_DISCLOSURE}/data",
            params={"section": "danpan"}, timeout=20,
        )
        resp.raise_for_status()
        sites = resp.json().get('sites', [])
    except Exception as e:
        sites_error = f"주가현황 서버에서 현장 목록을 가져오지 못했습니다({e}) — 서버가 켜져 있는지 확인해주세요."

    site_meta = danpan_tracking_db.get_all_site_meta()
    fixed_cc = danpan_tracking_db.list_fixed_cc()
    return render_template(
        'danpan_mail.html', user=current_user(), recipients=recipients, last_sent=last_sent,
        sites=sites, sites_error=sites_error, site_meta=site_meta, fixed_cc=fixed_cc,
    )


@app.route('/admin/danpan-mail/site-meta/save', methods=['POST'])
@danpan_mail_access_required
def admin_danpan_mail_site_meta_save():
    site_name = request.form.get('site_name', '').strip()
    if not site_name:
        flash('현장명을 확인할 수 없습니다.', 'error')
        return redirect(url_for('admin_danpan_mail'))
    department = request.form.get('department', '').strip() or None
    manager = request.form.get('manager', '').strip() or None
    note = request.form.get('note', '').strip() or None
    cc_email = request.form.get('cc_email', '').strip() or None
    danpan_tracking_db.set_site_meta(site_name, department, manager, note, cc_email)
    flash(f"'{site_name}' 담당정보를 저장했습니다.", 'success')
    return redirect(url_for('admin_danpan_mail'))


@app.route('/admin/danpan-mail/fixed-cc/add', methods=['POST'])
@danpan_mail_access_required
def admin_danpan_mail_fixed_cc_add():
    email = request.form.get('email', '').strip()
    label = request.form.get('label', '').strip() or None
    if not email:
        flash('이메일을 입력해주세요.', 'error')
    else:
        danpan_tracking_db.add_fixed_cc(email, label)
        flash('고정 참조자를 추가했습니다.', 'success')
    return redirect(url_for('admin_danpan_mail'))


@app.route('/admin/danpan-mail/fixed-cc/delete/<int:cc_id>', methods=['POST'])
@danpan_mail_access_required
def admin_danpan_mail_fixed_cc_delete(cc_id):
    danpan_tracking_db.delete_fixed_cc(cc_id)
    flash('고정 참조자를 삭제했습니다.', 'info')
    return redirect(url_for('admin_danpan_mail'))


@app.route('/admin/danpan-mail/add', methods=['POST'])
@danpan_mail_access_required
def admin_danpan_mail_add():
    email = request.form.get('email', '').strip()
    label = request.form.get('label', '').strip() or None
    if not email:
        flash('이메일을 입력해주세요.', 'error')
    else:
        hub_db.add_danpan_mail_recipient(email, label)
        flash('수신자를 추가했습니다.', 'success')
    return redirect(url_for('admin_danpan_mail'))


@app.route('/admin/danpan-mail/delete/<int:recipient_id>', methods=['POST'])
@danpan_mail_access_required
def admin_danpan_mail_delete(recipient_id):
    hub_db.delete_danpan_mail_recipient(recipient_id)
    flash('수신자를 삭제했습니다.', 'info')
    return redirect(url_for('admin_danpan_mail'))


@app.route('/admin/danpan-mail/send-now', methods=['POST'])
@danpan_mail_access_required
def admin_danpan_mail_send_now():
    """관리자 화면에서 직접 눌러 즉시 발송 — 실제 현장 목록은 주가현황 서버에 있으므로
    이 허브에 접속한 주소를 그대로 재사용해 그 서버의 /data?section=danpan을 호출한다."""
    host = request.host.split(':')[0]
    try:
        resp = requests.get(
            f"http://{host}:{hub_config.PORT_STOCK_DISCLOSURE}/data",
            params={"section": "danpan"}, timeout=20,
        )
        resp.raise_for_status()
        sites = resp.json().get('sites', [])
    except Exception as e:
        flash(f'주가현황 서버에서 단판공시 현황을 가져오지 못했습니다 — 서버가 켜져 있는지 확인해주세요. ({e})', 'error')
        return redirect(url_for('admin_danpan_mail'))

    result = danpan_mail.send_monthly_mail(sites, triggered_by='manual')
    if result.get('ok'):
        cc_note = f", 참조 {result['cc_count']}명" if result.get('cc_count') else ''
        flash(f"{result['recipient_count']}명에게 발송했습니다(현장 {result['site_count']}건{cc_note}).", 'success')
    else:
        flash(result.get('reason', '발송에 실패했습니다.'), 'error')
    return redirect(url_for('admin_danpan_mail'))


@app.route('/admin/danpan-mail-access')
@admin_required
def admin_danpan_mail_access():
    """단판공시 메일링 설정 권한을 전체 관리자가 아닌 특정 담당자(예: 공시 담당자)에게
    지정하는 화면 — 전체 관리자 계정은 이미 항상 접근 가능하므로 목록에서 뺀다."""
    users = [u for u in hub_db.list_users() if not u[3]]
    granted_ids = hub_db.list_danpan_mail_admin_ids()
    return render_template('danpan_mail_access.html', users=users, granted_ids=granted_ids)


@app.route('/admin/danpan-mail-access/grant/<int:user_id>', methods=['POST'])
@admin_required
def admin_danpan_mail_access_grant(user_id):
    target = hub_db.get_user_by_id(user_id)
    if not target:
        flash('사용자를 찾을 수 없습니다.', 'error')
    else:
        hub_db.grant_danpan_mail_admin(user_id)
        flash(f"{target['display_name'] or target['username']}님에게 단판공시 메일링 설정 권한을 부여했습니다.", 'success')
    return redirect(url_for('admin_danpan_mail_access'))


@app.route('/admin/danpan-mail-access/revoke/<int:user_id>', methods=['POST'])
@admin_required
def admin_danpan_mail_access_revoke(user_id):
    target = hub_db.get_user_by_id(user_id)
    hub_db.revoke_danpan_mail_admin(user_id)
    if target:
        flash(f"{target['display_name'] or target['username']}님의 단판공시 메일링 설정 권한을 회수했습니다.", 'info')
    return redirect(url_for('admin_danpan_mail_access'))


@app.route('/admin/cashflow-mail')
@cashflow_plan_mail_access_required
def admin_cashflow_mail():
    recipients = hub_db.list_cashflow_plan_mail_recipients()
    last_sent = hub_db.get_last_cashflow_plan_mail()
    templates = hub_db.list_cashflow_plan_templates()
    return render_template(
        'cashflow_mail.html', user=current_user(), recipients=recipients, last_sent=last_sent,
        templates=templates, template_slots=hub_db.CASHFLOW_PLAN_TEMPLATE_SLOTS,
    )


@app.route('/finance/cashflow-send')
@cashflow_plan_mail_access_required
def finance_cashflow_send():
    """자금 탭 하위 '📝 자금관리' 화면 — 관리자 화면(수신자ㆍ서식ㆍ담당자 지정 같은
    '설정')과 분리해, 실제 협조전 임시저장 '실행'은 여기서만 한다."""
    recipients = hub_db.list_cashflow_plan_mail_recipients()
    last_sent = hub_db.get_last_cashflow_plan_mail()
    templates = hub_db.list_cashflow_plan_templates()
    return render_template(
        'cashflow_send.html', user=current_user(), recipients=recipients, last_sent=last_sent,
        templates=templates, template_slots=hub_db.CASHFLOW_PLAN_TEMPLATE_SLOTS,
    )


@app.route('/admin/cashflow-mail/add', methods=['POST'])
@cashflow_plan_mail_access_required
def admin_cashflow_mail_add():
    label = request.form.get('label', '').strip()
    email = request.form.get('email', '').strip() or None
    if not label:
        flash('이름/부서명을 입력해주세요 — 그룹웨어 참조자 검색에 이 이름을 그대로 씁니다.', 'error')
    else:
        hub_db.add_cashflow_plan_mail_recipient(email, label)
        flash('참조자를 추가했습니다.', 'success')
    return redirect(url_for('admin_cashflow_mail'))


@app.route('/admin/cashflow-mail/delete/<int:recipient_id>', methods=['POST'])
@cashflow_plan_mail_access_required
def admin_cashflow_mail_delete(recipient_id):
    hub_db.delete_cashflow_plan_mail_recipient(recipient_id)
    flash('수신자를 삭제했습니다.', 'info')
    return redirect(url_for('admin_cashflow_mail'))


@app.route('/admin/cashflow-mail/template/upload', methods=['POST'])
@cashflow_plan_mail_access_required
def admin_cashflow_mail_template_upload():
    slot = request.form.get('slot', '').strip()
    valid_slots = {s for s, _ in hub_db.CASHFLOW_PLAN_TEMPLATE_SLOTS}
    file = request.files.get('template_file')
    if slot not in valid_slots:
        flash('알 수 없는 서식 종류입니다.', 'error')
    elif not file or not file.filename:
        flash('파일을 선택해주세요.', 'error')
    else:
        user = current_user()
        hub_db.save_cashflow_plan_template(
            slot, file.filename, file.read(),
            uploaded_by=user['display_name'] or user['username'],
        )
        flash(f"'{file.filename}' 서식을 등록했습니다.", 'success')
    return redirect(url_for('admin_cashflow_mail'))


@app.route('/admin/cashflow-mail/send-now', methods=['POST'])
@cashflow_plan_mail_access_required
def admin_cashflow_mail_send_now():
    # 메일 발송이 아니라 그룹웨어 협조전 임시저장으로 대체한다 — 자금계획 요청은
    # 실제로 메일이 아니라 협조전으로 주고받는 업무이기 때문. 로그인은 지금 이
    # 버튼을 누른 사람이 화면이 뜬 브라우저 창에서 직접 하고(포털은 그룹웨어
    # 로그인 정보를 전혀 저장하지 않는다), '임시저장'까지만 자동화한다 — 실제
    # 제출(기안)은 사람이 그룹웨어에서 마지막으로 확인 후 직접 눌러야 한다.
    user = current_user()
    sender_name = user['display_name'] or user['username']
    draft = cashflow_plan_mail.prepare_groupware_draft(sender_name)
    if not draft.get('ok'):
        flash(draft.get('reason', '협조전 작성 준비에 실패했습니다.'), 'error')
        return redirect(url_for('admin_cashflow_mail'))

    import groupware_rpa
    result = groupware_rpa.create_groupware_draft(
        subject=draft['subject'], body_html=draft['body_html'],
        recipient_labels=draft['recipient_labels'], attachments=draft['attachments'],
    )
    if result.get('ok'):
        hub_db.log_cashflow_plan_mail(
            year_month=datetime.now().strftime('%Y-%m'),
            recipient_count=len(draft['recipient_labels']), triggered_by='manual',
        )
        missing_note = f" (미등록 서식: {', '.join(draft['missing_templates'])})" if draft.get('missing_templates') else ''
        flash(f"{result['message']}{missing_note}", 'success')
    else:
        flash(result.get('reason', '협조전 작성에 실패했습니다.'), 'error')
    return redirect(url_for('admin_cashflow_mail'))


@app.route('/admin/ftc-disclosure-mail')
@ftc_disclosure_mail_access_required
def admin_ftc_disclosure_mail():
    recipients = hub_db.list_ftc_disclosure_mail_recipients()
    last_sent = hub_db.get_last_ftc_disclosure_mail()
    templates = hub_db.list_ftc_disclosure_templates()
    return render_template(
        'ftc_disclosure_mail.html', user=current_user(), recipients=recipients, last_sent=last_sent,
        templates=templates, template_slots=hub_db.FTC_DISCLOSURE_TEMPLATE_SLOTS,
    )


@app.route('/disclosure/ftc-send')
@ftc_disclosure_mail_access_required
def disclosure_ftc_send():
    """주가현황 공시 탭 '협조전 발송하기' 버튼이 여는 화면 — 관리자 설정(수신자ㆍ서식ㆍ
    담당자 지정)과 분리해, 실제 협조전 임시저장 '실행'은 여기서만 한다."""
    recipients = hub_db.list_ftc_disclosure_mail_recipients()
    last_sent = hub_db.get_last_ftc_disclosure_mail()
    templates = hub_db.list_ftc_disclosure_templates()
    period = ftc_disclosure_mail.compute_ftc_period()
    return render_template(
        'ftc_disclosure_send.html', user=current_user(), recipients=recipients, last_sent=last_sent,
        templates=templates, template_slots=hub_db.FTC_DISCLOSURE_TEMPLATE_SLOTS, period=period,
        title_preview=ftc_disclosure_mail.build_title(period),
    )


@app.route('/admin/ftc-disclosure-mail/add', methods=['POST'])
@ftc_disclosure_mail_access_required
def admin_ftc_disclosure_mail_add():
    label = request.form.get('label', '').strip()
    email = request.form.get('email', '').strip() or None
    if not label:
        flash('이름/부서명을 입력해주세요 — 그룹웨어 참조자 검색에 이 이름을 그대로 씁니다.', 'error')
    else:
        hub_db.add_ftc_disclosure_mail_recipient(email, label)
        flash('참조자를 추가했습니다.', 'success')
    return redirect(url_for('admin_ftc_disclosure_mail'))


@app.route('/admin/ftc-disclosure-mail/delete/<int:recipient_id>', methods=['POST'])
@ftc_disclosure_mail_access_required
def admin_ftc_disclosure_mail_delete(recipient_id):
    hub_db.delete_ftc_disclosure_mail_recipient(recipient_id)
    flash('수신자를 삭제했습니다.', 'info')
    return redirect(url_for('admin_ftc_disclosure_mail'))


@app.route('/admin/ftc-disclosure-mail/template/upload', methods=['POST'])
@ftc_disclosure_mail_access_required
def admin_ftc_disclosure_mail_template_upload():
    slot = request.form.get('slot', '').strip()
    valid_slots = {s for s, _ in hub_db.FTC_DISCLOSURE_TEMPLATE_SLOTS}
    file = request.files.get('template_file')
    if slot not in valid_slots:
        flash('알 수 없는 서식 종류입니다.', 'error')
    elif not file or not file.filename:
        flash('파일을 선택해주세요.', 'error')
    else:
        user = current_user()
        hub_db.save_ftc_disclosure_template(
            slot, file.filename, file.read(),
            uploaded_by=user['display_name'] or user['username'],
        )
        flash(f"'{file.filename}' 서식을 등록했습니다.", 'success')
    return redirect(url_for('admin_ftc_disclosure_mail'))


@app.route('/admin/ftc-disclosure-mail/send-now', methods=['POST'])
@ftc_disclosure_mail_access_required
def admin_ftc_disclosure_mail_send_now():
    # 자금계획 협조전(admin_cashflow_mail_send_now)과 완전히 같은 방식 — 메일 발송이 아니라
    # 그룹웨어 협조전 임시저장. 로그인은 지금 이 버튼을 누른 사람이 뜬 브라우저 창에서
    # 직접 하고, '임시저장'까지만 자동화한다 — 실제 제출(기안)은 사람이 그룹웨어에서
    # 마지막으로 확인 후 직접 눌러야 한다.
    user = current_user()
    sender_name = user['display_name'] or user['username']
    draft = ftc_disclosure_mail.prepare_groupware_draft(sender_name)
    if not draft.get('ok'):
        flash(draft.get('reason', '협조전 작성 준비에 실패했습니다.'), 'error')
        return redirect(url_for('disclosure_ftc_send'))

    import groupware_rpa
    result = groupware_rpa.create_groupware_draft(
        subject=draft['subject'], body_html=draft['body_html'],
        recipient_labels=draft['recipient_labels'], attachments=draft['attachments'],
    )
    if result.get('ok'):
        hub_db.log_ftc_disclosure_mail(
            period_label=draft['period_label'],
            recipient_count=len(draft['recipient_labels']), triggered_by='manual',
        )
        missing_note = f" (미등록 서식: {', '.join(draft['missing_templates'])})" if draft.get('missing_templates') else ''
        flash(f"{result['message']}{missing_note}", 'success')
    else:
        flash(result.get('reason', '협조전 작성에 실패했습니다.'), 'error')
    return redirect(url_for('disclosure_ftc_send'))


@app.route('/admin/ftc-disclosure-mail-access')
@admin_required
def admin_ftc_disclosure_mail_access():
    """공정위 공시 협조전 설정 권한을 전체 관리자가 아닌 특정 담당자에게 지정하는 화면."""
    users = [u for u in hub_db.list_users() if not u[3]]
    granted_ids = hub_db.list_ftc_disclosure_mail_admin_ids()
    return render_template('ftc_disclosure_mail_access.html', users=users, granted_ids=granted_ids)


@app.route('/admin/ftc-disclosure-mail-access/grant/<int:user_id>', methods=['POST'])
@admin_required
def admin_ftc_disclosure_mail_access_grant(user_id):
    target = hub_db.get_user_by_id(user_id)
    if not target:
        flash('사용자를 찾을 수 없습니다.', 'error')
    else:
        hub_db.grant_ftc_disclosure_mail_admin(user_id)
        flash(f"{target['display_name'] or target['username']}님에게 공정위 공시 협조전 설정 권한을 부여했습니다.", 'success')
    return redirect(url_for('admin_ftc_disclosure_mail_access'))


@app.route('/admin/ftc-disclosure-mail-access/revoke/<int:user_id>', methods=['POST'])
@admin_required
def admin_ftc_disclosure_mail_access_revoke(user_id):
    target = hub_db.get_user_by_id(user_id)
    hub_db.revoke_ftc_disclosure_mail_admin(user_id)
    if target:
        flash(f"{target['display_name'] or target['username']}님의 공정위 공시 협조전 설정 권한을 회수했습니다.", 'info')
    return redirect(url_for('admin_ftc_disclosure_mail_access'))


@app.route('/admin/cashflow-mail-access')
@admin_required
def admin_cashflow_mail_access():
    """자금계획 메일링 설정 권한을 전체 관리자가 아닌 특정 담당자에게 지정하는 화면 —
    담당자가 아직 정해지지 않아, 정해지면 관리자가 여기서 권한만 부여해주면 된다."""
    users = [u for u in hub_db.list_users() if not u[3]]
    granted_ids = hub_db.list_cashflow_plan_mail_admin_ids()
    return render_template('cashflow_mail_access.html', users=users, granted_ids=granted_ids)


@app.route('/admin/cashflow-mail-access/grant/<int:user_id>', methods=['POST'])
@admin_required
def admin_cashflow_mail_access_grant(user_id):
    target = hub_db.get_user_by_id(user_id)
    if not target:
        flash('사용자를 찾을 수 없습니다.', 'error')
    else:
        hub_db.grant_cashflow_plan_mail_admin(user_id)
        flash(f"{target['display_name'] or target['username']}님에게 자금계획 메일링 설정 권한을 부여했습니다.", 'success')
    return redirect(url_for('admin_cashflow_mail_access'))


@app.route('/admin/cashflow-mail-access/revoke/<int:user_id>', methods=['POST'])
@admin_required
def admin_cashflow_mail_access_revoke(user_id):
    target = hub_db.get_user_by_id(user_id)
    hub_db.revoke_cashflow_plan_mail_admin(user_id)
    if target:
        flash(f"{target['display_name'] or target['username']}님의 자금계획 메일링 설정 권한을 회수했습니다.", 'info')
    return redirect(url_for('admin_cashflow_mail_access'))


@app.route('/admin/create-user', methods=['POST'])
@admin_required
def admin_create_user():
    username = request.form.get('new_username', '').strip()
    display_name = request.form.get('new_display_name', '').strip()
    team = request.form.get('new_team', '').strip()
    password = request.form.get('new_password', '').strip() or None
    if not username or not display_name or not team:
        flash('아이디, 이름, 팀명은 필수입니다.', 'error')
        return redirect(url_for('admin'))
    email = mailer.email_for_username(username)
    result = hub_db.create_user_directly(username, display_name, password, team=team, email=email)
    if not result:
        flash('이미 사용 중인 아이디입니다.', 'error')
    else:
        mail_result = mailer.send_mail(
            email,
            '[통합 자금포털] 계정이 생성되었습니다',
            f"{display_name}님,\n\n통합 자금포털 계정이 생성되었습니다.\n"
            f"아이디: {result['username']}\n초기 비밀번호: {result['password']}\n\n로그인 후 '내 정보'에서 비밀번호를 변경해주세요.",
        )
        session['new_credential'] = result
        session['new_credential_mail'] = mail_result
        flash(f"{result['username']} 계정을 생성했습니다.", 'success')
    return redirect(url_for('admin'))


@app.route('/admin/approve/<int:request_id>', methods=['POST'])
@admin_required
def admin_approve(request_id):
    password = request.form.get('password', '').strip() or None
    pending_row = next((r for r in hub_db.list_requests(status='pending') if r[0] == request_id), None)
    email = mailer.email_for_username(pending_row[1]) if pending_row else None
    result = hub_db.approve_request(request_id, password, email=email)
    if not result:
        flash('요청을 찾을 수 없습니다.', 'error')
    elif result.get('error') == 'duplicate_username':
        flash('이미 같은 아이디의 계정이 있습니다. 요청자에게 다른 아이디로 다시 요청해달라고 안내해주세요.', 'error')
    else:
        mail_result = mailer.send_mail(
            email,
            '[통합 자금포털] 계정이 승인되었습니다',
            f"통합 자금포털 접근 요청이 승인되었습니다.\n"
            f"아이디: {result['username']}\n초기 비밀번호: {result['password']}\n\n로그인 후 '내 정보'에서 비밀번호를 변경해주세요.",
        )
        session['new_credential'] = result
        session['new_credential_mail'] = mail_result
        flash(f"{result['username']} 계정을 승인했습니다.", 'success')
    return redirect(url_for('admin'))


@app.route('/admin/reject/<int:request_id>', methods=['POST'])
@admin_required
def admin_reject(request_id):
    hub_db.reject_request(request_id)
    flash('요청을 거절했습니다.', 'info')
    return redirect(url_for('admin'))


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == current_user()['id']:
        flash('본인 계정은 여기서 삭제할 수 없습니다.', 'error')
    else:
        hub_db.delete_user(user_id)
        flash('계정을 삭제했습니다.', 'info')
    return redirect(url_for('admin'))


@app.route('/admin/toggle-admin/<int:user_id>', methods=['POST'])
@admin_required
def admin_toggle_admin(user_id):
    if user_id == current_user()['id']:
        flash('본인 계정의 관리자 권한은 여기서 바꿀 수 없습니다.', 'error')
        return redirect(url_for('admin'))
    users = {u[0]: u for u in hub_db.list_users()}
    target = users.get(user_id)
    if target:
        hub_db.set_admin(user_id, not bool(target[3]))
        flash('권한을 변경했습니다.', 'success')
    return redirect(url_for('admin'))


@app.route('/finance/<category>')
@login_required
def finance_view(category):
    cat = FINANCE_CATEGORIES.get(category)
    if not cat:
        return "알 수 없는 항목입니다.", 404
    user = current_user()
    selected, all_reports = _select_report_row(_parse_report_id_arg())
    sheet_pages = None
    report_label = None
    ftc_review = None
    ftc_capital_base = None
    invest_summary = None
    lend_affiliate_summary = None
    if selected:
        report_label = selected[3]
        wb = report_shared.load_workbook_from_bytes(report_db.get_report_bytes(selected[0]), data_only=True)
        sheet_names = cat['sheets'] if 'sheets' in cat else [cat['sheet']]
        pages = [
            {'title': name, 'html': report_shared.render_sheet_html(wb[name])}
            for name in sheet_names if name in wb.sheetnames
        ]
        sheet_pages = pages or None
        if category == 'lend' and cat.get('sheet') in wb.sheetnames:
            ftc_review, ftc_capital_base = _compute_lend_ftc_review(wb[cat['sheet']])
            lend_affiliate_summary = _compute_lend_affiliate_summary(wb[cat['sheet']])
        if category == 'invest' and cat.get('sheet') in wb.sheetnames:
            invest_summary = report_shared.compute_invest_summary(wb[cat['sheet']])
    subnav = [
        {'category': c, 'label': FINANCE_CATEGORIES[c]['label']} for c in REPORT_SUBNAV
    ]
    return render_template(
        'finance_view.html', user=user, category=category, cat=cat,
        sheet_pages=sheet_pages, report_label=report_label,
        all_reports=all_reports, selected_report_id=(selected[0] if selected else None),
        ftc_review=ftc_review, ftc_capital_base=ftc_capital_base,
        invest_summary=invest_summary, lend_affiliate_summary=lend_affiliate_summary, subnav=subnav,
    )


@app.route('/finance/<category>/edit')
@admin_required
def finance_edit(category):
    cat = FINANCE_CATEGORIES.get(category)
    if not cat or not cat.get('editable'):
        return "알 수 없는 항목입니다.", 404
    user = current_user()
    selected, _ = _select_report_row(_parse_report_id_arg())
    if not selected:
        flash('먼저 월간보고서를 업로드해주세요.', 'error')
        return redirect(url_for('finance_view', category=category))
    wb = report_shared.load_workbook_from_bytes(report_db.get_report_bytes(selected[0]), data_only=True)
    if cat['sheet'] not in wb.sheetnames:
        flash('해당 시트를 파일에서 찾을 수 없습니다.', 'error')
        return redirect(url_for('finance_view', category=category))
    table_html = report_shared.render_sheet_editable_html(wb[cat['sheet']])
    return render_template(
        'finance_edit.html', user=user, category=category, cat=cat,
        table_html=table_html, report_id=selected[0], report_label=selected[3],
    )


@app.route('/finance/<category>/save', methods=['POST'])
@admin_required
def finance_save(category):
    cat = FINANCE_CATEGORIES.get(category)
    if not cat or not cat.get('editable'):
        return jsonify({"ok": False, "error": "알 수 없는 항목입니다."}), 404

    payload = request.get_json(force=True, silent=True) or {}
    try:
        max_row = int(payload.get('max_row', 0))
        max_col = int(payload.get('max_col', 0))
        report_id = int(payload['report_id']) if payload.get('report_id') else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "잘못된 요청입니다."}), 400
    values = payload.get('values') or {}
    if max_row <= 0 or max_col <= 0:
        return jsonify({"ok": False, "error": "잘못된 요청입니다."}), 400

    selected, _ = _select_report_row(report_id)
    if not selected:
        return jsonify({"ok": False, "error": "먼저 월간보고서를 업로드해주세요."}), 400

    # data_only=False로 다시 열어 편집하지 않는 다른 시트의 수식은 그대로 보존한다.
    wb = report_shared.load_workbook_from_bytes(report_db.get_report_bytes(selected[0]))
    report_shared.apply_grid_edits_to_workbook(wb, cat['sheet'], max_row, max_col, values)
    new_bytes = report_shared.workbook_to_bytes(wb)
    report_db.save_report(selected[1], selected[2], f"{cat['sheet']}_수정.xlsx", new_bytes)
    return jsonify({"ok": True})


@app.route('/finance/<category>/upload', methods=['POST'])
@admin_required
def finance_upload(category):
    cat = FINANCE_CATEGORIES.get(category)
    if not cat:
        return "알 수 없는 항목입니다.", 404
    try:
        year = int(request.form.get('year', ''))
        month = int(request.form.get('month', ''))
    except ValueError:
        flash('연도/월을 확인해주세요.', 'error')
        return redirect(url_for('finance_view', category=category))
    file = request.files.get('report_file')
    if not file or not file.filename:
        flash('업로드할 엑셀 파일을 선택해주세요.', 'error')
        return redirect(url_for('finance_view', category=category))
    report_db.save_report(year, month, file.filename, file.read())
    flash(f'{year}년 {month}월 월간보고서를 저장했습니다.', 'success')
    return redirect(url_for('finance_view', category=category))


@app.route('/finance/admin')
@admin_required
def finance_admin():
    user = current_user()
    reports = report_db.list_reports()
    return render_template('finance_admin.html', user=user, reports=reports, categories=FINANCE_CATEGORIES)


@app.route('/finance/admin/upload', methods=['POST'])
@admin_required
def finance_admin_upload():
    try:
        year = int(request.form.get('year', ''))
        month = int(request.form.get('month', ''))
    except ValueError:
        flash('연도/월을 확인해주세요.', 'error')
        return redirect(url_for('finance_admin'))
    file = request.files.get('report_file')
    if not file or not file.filename:
        flash('업로드할 엑셀 파일을 선택해주세요.', 'error')
        return redirect(url_for('finance_admin'))
    report_db.save_report(year, month, file.filename, file.read())
    flash(f'{year}년 {month}월 월간보고서를 저장했습니다.', 'success')
    return redirect(url_for('finance_admin'))


@app.route('/finance/admin/download/<int:report_id>')
@admin_required
def finance_admin_download(report_id):
    data = report_db.get_report_bytes(report_id)
    if data is None:
        flash('파일을 찾을 수 없습니다.', 'error')
        return redirect(url_for('finance_admin'))
    row = next((r for r in report_db.list_reports() if r[0] == report_id), None)
    filename = (row[4] if row and row[4] else f"monthly_report_{report_id}.xlsx")
    if not filename.lower().endswith('.xlsx'):
        filename += '.xlsx'
    # 한글 파일명은 filename*=UTF-8''(RFC 5987)로 인코딩해야 모든 브라우저에서 깨지지 않는다.
    from urllib.parse import quote
    encoded_filename = quote(filename)
    return Response(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f"attachment; filename=\"report.xlsx\"; filename*=UTF-8''{encoded_filename}"},
    )


@app.route('/finance/admin/delete/<int:report_id>', methods=['POST'])
@admin_required
def finance_admin_delete(report_id):
    report_db.delete_report(report_id)
    flash('삭제했습니다.', 'info')
    return redirect(url_for('finance_admin'))


def _cashflow_plan_mail_auto_loop():
    """매월 1일에 자금계획 3개월 요청 메일을 자동 발송한다. danpan_mail과 달리
    현황 데이터를 다른 서버에서 가져올 필요가 없어(고정 수신자 + 고정 서식 첨부)
    이 허브 프로세스 안에서 바로 돈다. 서식이 그 달에 아직 안 올라와 있으면
    send_monthly_mail이 실패로 반환하니, 그 경우엔 이번 점검 주기에 조용히 건너뛰고
    다음 점검(6시간 뒤)에 다시 시도한다 — 담당자가 늦게라도 서식을 올리면 그 날 안에
    자동으로 발송된다."""
    while True:
        try:
            if datetime.now().day >= 1 and not cashflow_plan_mail.already_sent_this_month():
                result = cashflow_plan_mail.send_monthly_mail(triggered_by='auto')
                if result.get('ok'):
                    print(f"[자금계획 자동발송] {result['recipient_count']}명에게 서식 {result['attachment_count']}건 발송")
                else:
                    print(f"[자금계획 자동발송 건너뜀] {result.get('reason')}")
        except Exception as e:
            print(f"[자금계획 자동발송 실패] {e}")
        _time_module.sleep(6 * 60 * 60)


if __name__ == '__main__':
    threading.Thread(target=_cashflow_plan_mail_auto_loop, daemon=True).start()
    # debug=False로 둡니다: 이 허브는 사내망의 다른 사람들도 접속하는 로그인 화면이라,
    # Flask/Werkzeug 디버그 모드의 대화형 콘솔(에러 발생 시 브라우저에서 코드 실행 가능)이
    # 외부(같은 네트워크의 누구든)에 노출되면 안 됩니다.
    app.run(host='0.0.0.0', port=hub_config.HUB_PORT, debug=False, threaded=True)
