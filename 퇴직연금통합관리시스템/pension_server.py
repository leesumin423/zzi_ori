# -*- coding: utf-8 -*-
"""퇴직연금 대시보드 서버(Flask). 예전 run_dashboard.py는 파이썬 내장 http.server로
정적 파일만 서빙하고 data.json은 서버 시작 시 딱 한 번만 만들었는데, 그러면 관리자가
기준일을 추가하려면 parse_data.py의 BASE_DATES를 직접 고치고 서버를 재시작해야 했다.
이제 pension_db.py(SQLite)에 등록한 기준일은 /data.json 요청마다 즉석에서 반영된다
(관리자 화면은 /admin — 비밀번호는 pension_config.py)."""
import io
import os
import time
from datetime import datetime

from flask import (
    Flask, request, session, redirect, url_for, flash,
    send_from_directory, jsonify, render_template, get_flashed_messages,
)

import openpyxl

import parse_data
import pension_db
import pension_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = 'pension-dashboard-local-secret'  # 이 PC/LAN 내부용 — 외부 노출 안 됨

_DATA_CACHE_TTL = 300  # 초 — 레거시 파일이 그새 바뀌었을 가능성 대비, 업로드 시엔 즉시 무효화
_data_cache = {"data": None, "ts": 0.0}


def _get_data():
    now = time.time()
    if _data_cache["data"] is None or now - _data_cache["ts"] > _DATA_CACHE_TTL:
        _data_cache["data"] = parse_data.build_snapshots_and_yoy()
        _data_cache["ts"] = now
    return _data_cache["data"]


def _invalidate_cache():
    _data_cache["data"] = None


def _is_admin():
    return session.get('pension_admin') is True


@app.route('/data.json')
def data_json():
    return jsonify(_get_data())


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == pension_config.ADMIN_PASSWORD:
            session['pension_admin'] = True
        else:
            flash('비밀번호가 올바르지 않습니다.', 'error')
        return redirect(url_for('admin'))
    reports = pension_db.list_reports()
    return render_template(
        'pension_admin.html', authed=_is_admin(), reports=reports,
        messages=get_flashed_messages(with_categories=True),
    )


@app.route('/admin/upload', methods=['POST'])
def admin_upload():
    if not _is_admin():
        return redirect(url_for('admin'))

    base_date = request.form.get('base_date', '').strip()
    label = request.form.get('label', '').strip()
    sheet_hint = request.form.get('sheet_hint', '').strip()
    file = request.files.get('excel_file')

    if not base_date or not label or not sheet_hint or not file or not file.filename:
        flash('기준일ㆍ라벨ㆍ시트명 힌트ㆍ엑셀 파일을 모두 입력해주세요.', 'error')
        return redirect(url_for('admin'))
    try:
        datetime.strptime(base_date, '%Y-%m-%d')
    except ValueError:
        flash('기준일 형식이 올바르지 않습니다.', 'error')
        return redirect(url_for('admin'))

    file_bytes = file.read()
    # 저장하기 전에 실제로 파싱되는지 먼저 확인한다 — 이 서식은 시트명/열 위치가
    # 조금만 달라져도 깨지기 쉬워서, 잘못된 파일을 저장해뒀다가 대시보드 전체가
    # 조용히 깨지는 것보다 업로드 시점에 바로 알려주는 편이 낫다.
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        parse_data.parse_sheet_data_from_workbook(wb, sheet_hint, base_date)
    except Exception as e:
        flash(f'파싱 실패: {e} — 시트명 힌트를 확인해주세요.', 'error')
        return redirect(url_for('admin'))

    pension_db.save_report(base_date, label, sheet_hint, file.filename, file_bytes)
    _invalidate_cache()
    flash(f'{label} ({base_date}) 데이터를 저장했습니다.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/delete/<int:report_id>', methods=['POST'])
def admin_delete(report_id):
    if not _is_admin():
        return redirect(url_for('admin'))
    pension_db.delete_report(report_id)
    _invalidate_cache()
    flash('삭제했습니다.', 'info')
    return redirect(url_for('admin'))


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('pension_admin', None)
    return redirect(url_for('admin'))


@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)
