import os
import re
import json
import io
import zipfile
from datetime import date, datetime, time as dtime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────────────────────
# DART(전자공시) Open API 키 — 절대 코드에 직접 적지 않고 환경변수나
# .gitignore된 로컬 파일(.dart_api_key)에서만 읽는다. 둘 다 없으면 DART
# 조회 기능은 자동으로 꺼지고(값이 ''), 나머지 기능은 그대로 동작한다.
# 키 발급: https://opendart.fss.or.kr (가입 즉시 무료 발급, 승인 대기 없음)
def _load_dart_api_key() -> str:
    key = os.getenv('DART_API_KEY', '').strip()
    if key:
        return key
    key_file = os.path.join(BASE_DIR, '.dart_api_key')
    if os.path.exists(key_file):
        with open(key_file, encoding='utf-8') as f:
            return f.read().strip()
    return ''

DART_API_KEY = _load_dart_api_key()

# ─────────────────────────────────────────────────────────────
# 정적 파일 서빙 (HTML/CSS/JS) — 이 라우트 덕분에 python server.py
# 하나만 실행해도 http://localhost:5000 에서 대시보드가 통째로 열림
# ─────────────────────────────────────────────────────────────
@app.after_request
def no_cache(response):
    # html/css/js를 브라우저가 캐싱하면 server.py를 껐다 켜도 예전 화면이 보일 수
    # 있어서(수정한 스타일이 안 바뀐 것처럼 보임), 이 앱은 항상 최신 파일을 받도록 함
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/')
def index():
    for candidate in ('주가현황.html', 'index.html'):
        if os.path.exists(os.path.join(BASE_DIR, candidate)):
            return send_from_directory(BASE_DIR, candidate)
    return (
        "HTML 파일을 찾을 수 없습니다. server.py와 같은 폴더에 "
        "'주가현황.html' 또는 'index.html' 파일이 있는지 확인하세요.",
        404,
    )

@app.route('/<path:filename>')
def static_files(filename):
    # /data 같은 API 라우트는 아래에서 더 구체적으로 매칭되므로 겹치지 않음
    return send_from_directory(BASE_DIR, filename)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://finance.naver.com/',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

# ─────────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────────
def fmt_num(val, decimal=2):
    """숫자 포맷 (천 단위 콤마)"""
    try:
        v = float(str(val).replace(',', ''))
        if decimal == 0:
            return f"{int(v):,}"
        return f"{v:,.{decimal}f}"
    except Exception:
        return str(val)

def direction_symbol(name: str) -> str:
    """'RISING'/'FALLING' -> arrow unicode"""
    if 'RISING' in name or 'UPPER_LIMIT' in name:
        return '\u2191'  # ↑
    if 'FALLING' in name or 'LOWER_LIMIT' in name:
        return '\u2193'  # ↓
    return '-'

def is_krx_open() -> bool:
    """KRX 정규장(평일 09:00~15:30) 진행 중 여부 — 공휴일은 고려하지 않음"""
    now = datetime.now()
    if now.weekday() >= 5:  # 토(5)/일(6)
        return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)

def is_nxt_extended_hours() -> bool:
    """넥스트레이드(NXT, 대체거래소)가 KRX 정규장 앞뒤로 별도 운영하는 시간대인지
    — 프리마켓(08:00~09:00)ㆍ애프터마켓(15:30~20:00). 이 시간대엔 KRX가 쉬거나
    이미 마감했어도 NXT에서 그 종목이 거래되고 있으면 가격이 계속 바뀔 수 있다.
    공휴일은 고려하지 않는다(is_krx_open과 동일한 한계)."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(8, 0) <= t < dtime(9, 0) or dtime(15, 30) < t <= dtime(20, 0)

def _parse_rate_info_block(soup, div_id: str):
    """finance.naver.com/item/main.naver 페이지에는 KRX 탭용(id="rate_info_krx")과
    NXT 탭용(id="rate_info_nxt") 시세 블록이 항상 둘 다 서버사이드에 렌더링돼
    있고(탭 전환은 둘 중 하나를 보이기/숨기기만 하는 순수 클라이언트 동작), 접근성용
    <dl class="blind"> 안에 "오늘의시세 N 포인트 / N 포인트 상승|하락|보합 / N%
    플러스|마이너스" 형태로 항상 텍스트가 붙어있다 — 화면에 보이는 자릿수별
    <span>을 일일이 세는 것보다 이 숨은 텍스트를 파싱하는 게 안정적이다. NXT
    비대상 종목이거나 원문 구조가 바뀌면 None."""
    div = soup.find('div', id=div_id)
    if not div:
        return None
    dl = div.find('dl', class_='blind')
    if not dl:
        return None
    dds = [dd.get_text(strip=True) for dd in dl.find_all('dd')]
    if len(dds) < 3:
        return None
    price_m = re.search(r'([\d,]+)', dds[0])
    diff_m = re.search(r'([\d,]+)', dds[1])
    rate_m = re.search(r'([\d.]+)', dds[2])
    if not price_m:
        return None
    price = int(price_m.group(1).replace(',', ''))
    diff = int(diff_m.group(1).replace(',', '')) if diff_m else 0
    rate = float(rate_m.group(1)) if rate_m else 0.0
    if '하락' in dds[1] or '마이너스' in dds[2]:
        diff, rate = -diff, -rate
    return {'price': price, 'diff': diff, 'rate': rate}

# ─────────────────────────────────────────────────────────────
# 1. 지수 (KOSPI / KOSDAQ)
# ─────────────────────────────────────────────────────────────
def fetch_index_close_basis(code: str, market_open: bool):
    """
    fchart 일봉 데이터로 '직전 확정 거래일'의 종가와, 그 하루 전 종가 대비
    등락(포인트/퍼센트)을 계산 — 현재기준(polling API)과 동일한 형태로
    색상/등락폭을 보여주기 위함.
    장이 열려있으면 당일 봉은 아직 미확정이므로 제외하고 그 앞 봉을 확정치로 사용.
    """
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=10&requestType=0"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'xml')
        rows = []
        for item in soup.find_all('item'):
            parts = item.get('data', '').split('|')
            if len(parts) < 5:
                continue
            rows.append(float(parts[4]))  # close

        idx = len(rows) - 1
        if market_open:
            idx -= 1  # 당일 봉은 미확정이므로 제외
        if idx < 1:
            return None

        confirmed_close = rows[idx]
        prev_close = rows[idx - 1]
        diff = confirmed_close - prev_close
        ratio = (diff / prev_close * 100) if prev_close else 0
        return confirmed_close, diff, ratio
    except Exception as e:
        print(f"[DEBUG] {code} 장마감기준 지수 조회 중 예외: {e}")
        return None

def fetch_index(code: str) -> dict:
    """
    polling API로 지수 현황(현재기준) + fchart 일봉으로 직전 확정 종가 기준
    등락(장마감기준) + 투자자 동향 요약
    """
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        d = r.json()['datas'][0]
    except Exception as e:
        na = {"value": "N/A", "detail": str(e), "direction": ""}
        return {"current": na, "close": na}

    close = d.get('closePrice', 'N/A')
    diff  = d.get('compareToPreviousClosePrice', '0')
    ratio = d.get('fluctuationsRatio', '0')
    direction_name = d.get('compareToPreviousPrice', {}).get('name', '')
    direction = direction_symbol(direction_name)
    market_open = d.get('marketStatus') == 'OPEN'

    investors = fetch_investor_trend(code)
    inv_summary = investor_summary(investors)

    try:
        ratio_f = float(str(ratio).replace(',', ''))
        diff_f  = float(str(diff).replace(',', ''))
        sign = '+' if diff_f > 0 else ''
        change_detail = f"{sign}{fmt_num(diff_f, 2)} ({sign}{fmt_num(ratio_f, 2)}% {direction})"
    except Exception:
        change_detail = f"{diff} ({ratio}% {direction})"

    detail_current = f"{inv_summary}, {change_detail}" if inv_summary else change_detail
    value_current = f"{close}p {direction}"

    close_basis = fetch_index_close_basis(code, market_open)
    if close_basis is not None:
        confirmed_close, close_diff, close_ratio = close_basis
        close_direction = '↑' if close_diff > 0 else ('↓' if close_diff < 0 else '-')
        close_sign = '+' if close_diff > 0 else ''
        close_change_detail = (
            f"{close_sign}{fmt_num(close_diff, 2)} ({close_sign}{fmt_num(close_ratio, 2)}% {close_direction})"
        )
        value_close = f"{fmt_num(confirmed_close, 2)}p {close_direction}"
        detail_close = f"{inv_summary}, {close_change_detail}" if inv_summary else close_change_detail
    else:
        value_close, detail_close, close_direction = value_current, detail_current, direction

    return {
        "current": {"value": value_current, "detail": detail_current, "direction": direction},
        "close":   {"value": value_close,   "detail": detail_close,   "direction": close_direction},
    }

def fetch_investor_trend(code: str) -> dict:
    """KOSPI/KOSDAQ 투자자별(개인/외국인/기관계) 순매매 금액 반환 (네이버 증권 홈에서 추출)"""
    url = "https://finance.naver.com/"
    investors = {}
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        raw = r.content.decode('euc-kr', errors='replace')
        soup = BeautifulSoup(raw, 'html.parser')

        area_class = 'kospi_area' if code == 'KOSPI' else 'kosdaq_area'
        area = soup.find('div', class_=area_class)
        
        if not area:
            print(f"[DEBUG] {code} 투자자동향: '{area_class}' 영역을 찾지 못함")
            return investors

        target_dl = None
        for dl in area.find_all('dl'):
            txt = dl.get_text()
            if '개인' in txt and '외국인' in txt:
                target_dl = dl
                break

        if not target_dl:
            print(f"[DEBUG] {code} 투자자동향: 데이터 dl 태그를 찾지 못함")
            return investors

        dts = target_dl.find_all('dt')
        dds = target_dl.find_all('dd')
        
        for dt, dd in zip(dts, dds):
            key = dt.get_text(strip=True)
            val_str = dd.get_text(strip=True).replace('억원', '').replace(',', '').replace('+', '')
            if key in ['개인', '외국인', '기관']:
                try:
                    display_key = '기관합계' if key == '기관' else key
                    investors[display_key] = float(val_str)
                except Exception as pe:
                    print(f"[DEBUG] {code} '{key}' 파싱 실패: {val_str} ({pe})")

    except Exception as e:
        print(f"[DEBUG] {code} 투자자동향 조회 중 예외: {e}")
    return investors


def investor_summary(investors: dict) -> str:
    """{'개인': -100, '외국인': -50, '기관합계': 30} -> '외인, 기관 순매도'"""
    if not investors:
        return ''
    NAME_MAP = {'외국인': '외인', '기관합계': '기관', '개인': '개인'}
    sellers = [NAME_MAP[k] for k, v in investors.items() if v < 0]
    buyers  = [NAME_MAP[k] for k, v in investors.items() if v > 0]
    parts = []
    if sellers:
        parts.append(f"{', '.join(sellers)} 순매도")
    if buyers:
        parts.append(f"{', '.join(buyers)} 순매수")
    return ' / '.join(parts)

# ─────────────────────────────────────────────────────────────
# 2. 테마별 시세
# ─────────────────────────────────────────────────────────────
def fetch_theme_rate(no: int):
    """테마 그룹 페이지에서 전일대비 등락률(%)을 float로 반환. 조회 실패 시 None."""
    url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        raw = r.content.decode('utf-8', errors='replace')
        soup = BeautifulSoup(raw, 'html.parser')
        first_num = soup.select_one('td.number span')
        if not first_num:
            return None
        return float(first_num.get_text(strip=True).replace('%', '').replace('+', ''))
    except Exception as e:
        print(f"[DEBUG] \ud14c\ub9c8(no={no}) \ub4f1\ub77d\ub960 \uc870\ud68c \uc911 \uc608\uc678: {e}")
        return None

def _fmt_theme_rate(rate) -> str:
    if rate is None:
        return 'N/A'
    arrow = '\u2191' if rate > 0 else '\u2193' if rate < 0 else '-'
    sign = '+' if rate > 0 else ''
    return f"{sign}{rate:.2f}% {arrow}"

def _theme_market_closed_now() -> bool:
    """\uc774 \uc2dc\uc810\uc5d0 \uc870\ud68c\ud55c \ud14c\ub9c8 \ub4f1\ub77d\ub960\uc774 "\uadf8\ub0a0\uc758 \ud655\uc815\uce58"\ub85c \ucde8\uae09\ud574\ub3c4 \ub418\ub294 \uc2dc\uac04\ub300\uc778\uc9c0 \u2014
    KRX \uc815\uaddc\uc7a5 \ub9c8\uac10(15:30) \uc774\ud6c4, \ub610\ub294 \uc8fc\ub9d0(\uc9c1\uc804 \ud3c9\uc77c \ub9c8\uac10\uce58\uac00 \uadf8\ub300\ub85c \uc720\uc9c0 \uc911)."""
    now = datetime.now()
    if now.weekday() >= 5:
        return True
    return now.time() > dtime(15, 30)

_theme_daily_cache = {}  # no -> {"date": "YYYY-MM-DD", "rate": float}

def fetch_theme_change(no: int) -> dict:
    """\ud14c\ub9c8\uc758 \ud604\uc7ac\uae30\uc900(\uc624\ub298 \uc2e4\uc2dc\uac04 \ub4f1\ub77d\ub960)\u318d\uc7a5\ub9c8\uac10\uae30\uc900(\uc9c1\uc804 \ud655\uc815 \uac70\ub798\uc77c\uc758 \ucd5c\uc885
    \ub4f1\ub77d\ub960 \u2014 \uc7a5\uc774 \uc5f4\ub824\uc788\ub294 \ub3d9\uc548\uc740 \uc5b4\uc81c\uc790 \uac12, \ub9c8\uac10 \ud6c4\uc5d4 \uc624\ub298 \uac12\uacfc \ub3d9\uc77c) \ub4f1\ub77d\ub960\uc744
    \ud568\uaed8 \ubc18\ud658\ud55c\ub2e4.

    \ub124\uc774\ubc84 \ud14c\ub9c8 \uadf8\ub8f9 \ud398\uc774\uc9c0 \uc790\uccb4\uc5d4 \uac1c\ubcc4 \uc885\ubaa9\ucc98\ub7fc "\uc624\ub298/\uc804\uc77c" \ub450 \uac12\uc744 \ud568\uaed8 \uc8fc\ub294
    \uad6c\uc870\uac00 \uc5c6\uace0 \uadf8 \uc21c\uac04\uc758 \ub4f1\ub77d\ub960 \ud558\ub098\ub9cc \ub178\ucd9c\ud55c\ub2e4(\uacfc\uac70 \uc774\ub825\uc744 \ub418\uc9da\uc744 \uc218 \uc788\ub294
    \ud14c\ub9c8 \uc804\uc6a9 API\ub3c4 \ubabb \ucc3e\uc74c). \uadf8\ub798\uc11c \uc7a5\ub9c8\uac10\uae30\uc900\uc740 \uc774 \uc11c\ubc84\uac00 "\ub9c8\uac10 \uc774\ud6c4 \ucc98\uc74c
    \uc870\ud68c\ud55c \uac12"\uc744 \uadf8\ub0a0\uc758 \ud655\uc815\uce58\ub85c \uba54\ubaa8\ub9ac\uc5d0 \uce90\uc2dc\ud574\ub480\ub2e4\uac00, \ub2e4\uc74c\ub0a0 \uc7a5\uc911\uc5d0 \uadf8 \uac12\uc744
    \uc7a5\ub9c8\uac10\uae30\uc900\uc73c\ub85c \uc7ac\uc0ac\uc6a9\ud558\ub294 \ubc29\uc2dd\uc73c\ub85c \ub9cc\ub4e0\ub2e4 \u2014 \uc11c\ubc84\uac00 \uc7ac\uc2dc\uc791\ub418\uba74 \uce90\uc2dc\uac00
    \ube44\uc5b4 \uccab \uc870\ud68c \uc2dc\uc5d4 \uc7a5\ub9c8\uac10\uae30\uc900\uc774 \ud604\uc7ac\uac12\uacfc \uac19\uac8c \ub098\uc628\ub2e4(\uc774 \ud504\ub85c\uc81d\ud2b8\uc758 \ub2e4\ub978
    \uc778\uba54\ubaa8\ub9ac \uce90\uc2dc\ub4e4\ub3c4 \uc7ac\uc2dc\uc791 \uc2dc \ucd08\uae30\ud654\ub418\ub294 \uac83\uacfc \ub3d9\uc77c\ud55c \ud55c\uacc4)."""
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    rate = fetch_theme_rate(no)

    if _theme_market_closed_now():
        # \ub9c8\uac10 \ud6c4(\uc8fc\ub9d0 \ud3ec\ud568)\uc5d4 \uc9c0\uae08 \uac12\uc774 \uace7 "\uadf8\ub0a0\uc758 \ud655\uc815\uce58" \u2014 \uce90\uc2dc\ub97c \uac31\uc2e0
        if rate is not None:
            _theme_daily_cache[no] = {"date": today_str, "rate": rate}
        close_rate = rate
    else:
        entry = _theme_daily_cache.get(no)
        # \uce90\uc2dc\uac00 "\uc624\ub298 \ub0a0\uc9dc"\ub85c \ucc0d\ud600 \uc788\uc73c\uba74 \uc548 \ub428(\uadf8\ub7ec\uba74 \uc815\uc0c1\uc801\uc73c\ub85c\ub294 \ub9c8\uac10 \ud6c4\uc5d0\ub9cc
        # \uc0dd\uae30\ub294 \uc0c1\ud0dc\ub77c \uc55e\ub4a4\uac00 \uc548 \ub9de\ub294 \uac83) \u2014 \uc774\ub7f0 \uacbd\uc6b0\uc640 \uce90\uc2dc\uac00 \uc544\uc608 \uc5c6\ub294 \uacbd\uc6b0\uc5d4
        # \ud3f4\ubc31\uc73c\ub85c \ud604\uc7ac\uac12\uc744 \uadf8\ub300\ub85c \uc4f4\ub2e4(\uacfc\uac70 \ub3d9\uc791\uacfc \ub3d9\uc77c, \ucd5c\uc18c\ud55c \ud1f4\ubcf4\ub294 \uc544\ub2d8).
        close_rate = entry["rate"] if entry and entry["date"] != today_str else rate

    return {
        "current": _fmt_theme_rate(rate),
        "close": _fmt_theme_rate(close_rate),
    }

# ─────────────────────────────────────────────────────────────
# 3. 개별 종목 데이터
# ─────────────────────────────────────────────────────────────
def extract_labeled_value(soup, label_keywords):
    """페이지 내 (th/td) 또는 (dt/dd) 라벨-값 쌍에서 값 추출"""
    for row in soup.find_all('tr'):
        cells = row.find_all(['th', 'td'])
        for i, cell in enumerate(cells):
            text = cell.get_text(strip=True)
            if any(kw in text for kw in label_keywords) and i + 1 < len(cells):
                val = cells[i + 1].get_text(strip=True)
                if val:
                    return val
    for dl in soup.find_all('dl'):
        dts = dl.find_all('dt')
        dds = dl.find_all('dd')
        for dt, dd in zip(dts, dds):
            if any(kw in dt.get_text(strip=True) for kw in label_keywords):
                return dd.get_text(strip=True)
    return None

def extract_52w_high_low(soup):
    """
    main.naver 페이지의 '52주최고l최저' 행(th)에서 직접 고가/저가를 추출.
    (예전 방식은 fchart XML 최근 540봉(~2년치) 전체에서 max/min을 구해
    실제 네이버가 보여주는 '52주(1년)' 범위보다 넓은 구간의 값이 섞여 들어가는
    버그가 있었음 — 예: 성신양회 52주 최저가 6,830원(2025-04-07, 15개월 전) vs
    실제 52주 최저가 7,500원(2026-06-26). main 페이지 값을 그대로 쓰면 항상
    네이버 표시값과 일치한다.)
    """
    for th in soup.find_all('th'):
        text = th.get_text(strip=True)
        if '52주' in text and '최고' in text and '최저' in text:
            tr = th.find_parent('tr')
            if not tr:
                continue
            ems = tr.find_all('em')
            if len(ems) >= 2:
                return ems[0].get_text(strip=True), ems[1].get_text(strip=True)
    return None, None

def fetch_stock(ticker: str) -> dict:
    """
    itemSummary + fchart XML + main 페이지로 종목 데이터 수집
    - 현재가(현재기준): itemSummary.now
    - 15:30 장마감가(장마감기준): 장중이면 itemSummary.now - diff(=직전 확정 종가),
      장마감 후면 itemSummary.now 그대로 (그 값 자체가 이미 당일 종가로 고정됨)
    - 전년말 주가: fchart XML에서 전년(현재년도-1) 12월 마지막 거래일 종가
    - 52주 고/저: main 페이지의 '52주최고l최저' 표시값을 그대로 사용 (네이버와 일치)
    - 상장주식수: main 페이지 라벨(상장주식수) 탐색 (UTF-8)
    - 시가총액: 주식수 × 주가 (억 단위)
    - 진짜 조회 실패는 N/A, "전년 데이터 없음(신규상장 등)"만 0으로 표시
    """
    # 1) itemSummary (JSON)
    summary_url = f"https://api.finance.naver.com/service/itemSummary.nhn?itemcode={ticker}"
    try:
        sr = requests.get(summary_url, headers=HEADERS, timeout=10)
        summary = sr.json()
    except Exception as e:
        print(f"[DEBUG] {ticker} itemSummary 조회 실패: {e}")
        summary = {}

    price_current = summary.get('now', 0) or 0
    diff          = summary.get('diff', 0) or 0
    rate          = summary.get('rate', 0) or 0

    market_open = is_krx_open()
    price_close = (price_current - diff) if market_open else price_current

    # 2) fchart XML (전년말 주가 계산용, 최근 ~540봉)
    chart_url = (
        f"https://fchart.stock.naver.com/sise.nhn"
        f"?symbol={ticker}&timeframe=day&count=540&requestType=0"
    )
    last_year = date.today().year - 1
    price_prev_year = 0      # 없으면 0 (신규상장 등 정상 케이스)
    try:
        cr = requests.get(chart_url, headers=HEADERS, timeout=15)
        cr.encoding = 'euc-kr'
        soup = BeautifulSoup(cr.text, 'xml')
        items = soup.find_all('item')

        last_year_candidates = {}
        for item in items:
            parts = item.get('data', '').split('|')
            if len(parts) < 5:
                continue
            d_str, close = parts[0], parts[4]
            if d_str[:4] == str(last_year) and d_str[4:6] == '12' and int(d_str[6:8]) >= 24:
                last_year_candidates[d_str] = close

        if last_year_candidates:
            last_date = sorted(last_year_candidates.keys())[-1]
            price_prev_year = int(last_year_candidates[last_date])
    except Exception as e:
        print(f"[DEBUG] {ticker} fchart 조회 중 예외: {e}")

    # 3) 상장주식수 + 52주 최고/최저 + NXT 시세: main 페이지에서 함께 추출 (UTF-8)
    shares = 0
    high_52w = None
    low_52w  = None
    nxt_quote = None
    try:
        main_url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        mr = requests.get(main_url, headers=HEADERS, timeout=10)
        mr.encoding = 'utf-8'  # 핵심 수정: euc-kr -> utf-8
        msoup = BeautifulSoup(mr.text, 'html.parser')
        nxt_quote = _parse_rate_info_block(msoup, 'rate_info_nxt')  # NXT 비대상 종목이면 None

        raw_val = extract_labeled_value(msoup, ['상장주식수'])
        if raw_val:
            m = re.search(r'[\d,]+', raw_val)
            if m:
                shares = int(m.group(0).replace(',', ''))

        if not shares:
            full_text = msoup.get_text()
            m = re.search(r'상장주식수[^\d]*([0-9,]+)', full_text)
            if m:
                shares = int(m.group(1).replace(',', ''))

        if not shares:
            idx = mr.text.find('상장주식수')
            if idx == -1:
                print(f"[DEBUG] {ticker}: 응답에 '상장주식수' 문자열 없음 (구조변경/차단 가능성)")
            else:
                print(f"[DEBUG] {ticker} '상장주식수' 주변: {mr.text[max(0, idx-150):idx+250]}")

        high_raw, low_raw = extract_52w_high_low(msoup)
        if high_raw:
            high_52w = int(re.sub(r'[^\d]', '', high_raw) or 0) or None
        if low_raw:
            low_52w = int(re.sub(r'[^\d]', '', low_raw) or 0) or None
    except Exception as e:
        print(f"[DEBUG] {ticker} 상장주식수/52주 고저 조회 중 예외: {e}")

    # NXT(넥스트레이드) 프리마켓(08:00~09:00)ㆍ애프터마켓(15:30~20:00) 시간대에는
    # KRX가 쉬거나 이미 마감했어도 이 시간대엔 NXT가 그 종목의 "지금" 가격을 갖고
    # 있으므로, "현재기준"은 이 경우 NXT 시세로 덮어쓴다. "장마감기준"(price_close,
    # 위에서 이미 계산됨)은 KRX 정규장 15:30 종가 기준을 그대로 유지 — NXT와는
    # 무관한 값이라 여기서 건드리지 않는다.
    current_source = "KRX"
    if nxt_quote is not None and is_nxt_extended_hours():
        price_current = nxt_quote['price']
        diff = nxt_quote['diff']
        rate = nxt_quote['rate']
        current_source = "NXT"

    # 4) 시가총액(억원) / 등락율 — 현재기준·장마감기준 각각 계산
    def calc_marketcap(price):
        return round(shares * int(price) / 1_0000_0000) if shares and price else 0

    def calc_change_rate(marketcap, marketcap_prev):
        return round((marketcap - marketcap_prev) / marketcap_prev * 100, 2) if marketcap_prev else 0

    marketcap_current = calc_marketcap(price_current)
    marketcap_close = calc_marketcap(price_close)
    marketcap_prev = calc_marketcap(price_prev_year)

    change_rate_current = calc_change_rate(marketcap_current, marketcap_prev)
    change_rate_close = calc_change_rate(marketcap_close, marketcap_prev)

    arrow = '↑' if rate and float(rate) > 0 else '↓' if rate and float(rate) < 0 else '-'

    return {
        "ticker": ticker,
        "shares": f"{shares:,}",
        "price_prev_year": f"{price_prev_year:,}",
        "marketcap_prev": f"{marketcap_prev:,}",
        "high_52w": f"{high_52w:,}" if high_52w is not None else "N/A",
        "low_52w": f"{low_52w:,}" if low_52w is not None else "N/A",
        "daily_change": f"{diff:+,} ({rate:+.2f}% {arrow})" if diff and rate else "0 (0.00% -)",
        "current": {
            "price": f"{int(price_current):,}",
            "marketcap": f"{marketcap_current:,}",
            "change_rate": f"{change_rate_current:+.2f}%",
            "source": current_source,  # "KRX" 또는 "NXT"(프리마켓ㆍ애프터마켓 시간대에 NXT 시세로 대체됐을 때)
        },
        "close": {
            "price": f"{int(price_close):,}",
            "marketcap": f"{marketcap_close:,}",
            "change_rate": f"{change_rate_close:+.2f}%",
        },
    }

# ─────────────────────────────────────────────────────────────
# 3-1. 개별 종목 수급 동향 (기관/외국인 순매매)
# ─────────────────────────────────────────────────────────────
def _parse_signed_int(s: str) -> int:
    try:
        return int(str(s).replace(',', '').replace('+', ''))
    except Exception:
        return 0

def fetch_stock_investor(code: str, days: int = 5) -> list:
    """
    종목별 투자자매매동향 페이지(frgn.naver)에서 최근 N영업일 수급 동향 수집.
    이 페이지는 거래량/기관순매매/외국인순매매(모두 '주식 수')만 제공하고
    개인 순매매·거래대금은 없으므로:
    - 총거래대금(백만원) = 거래량 × 종가
    - 개인순매매(추정) = -(기관순매매 + 외국인순매매)  ※ 기타법인 등은 무시한 근사치
    """
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    result = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')

        # 표 개수/순서는 종목마다 다르다 (예: 투자유의종목 등은 '주요시세' 표가
        # 하나 더 붙어 뒤 표들이 한 칸씩 밀림 — 성신양회가 이 케이스라 tables[2]
        # 고정 인덱스로는 엉뚱한 표(거래원정보)를 집어 데이터가 안 나왔었음).
        # summary 속성으로 정확한 표를 찾는다.
        target = None
        for t in soup.find_all('table'):
            summary = t.get('summary', '') or ''
            if '외국인' in summary and '순매매' in summary:
                target = t
                break

        if target is None:
            print(f"[DEBUG] {code} 수급동향: '외국인 순매매' 표를 찾지 못함")
            return result

        for row in target.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            texts = [c.get_text(strip=True) for c in cells]
            if len(texts) != 9 or not re.match(r'^\d{4}\.\d{2}\.\d{2}$', texts[0]):
                continue

            close_val = _parse_signed_int(texts[1])
            volume_val = _parse_signed_int(texts[4])
            institution_val = _parse_signed_int(texts[5])
            foreign_val = _parse_signed_int(texts[6])
            individual_val = -(institution_val + foreign_val)
            total_value_million = round(close_val * volume_val / 1_000_000)

            result.append({
                "date": texts[0],
                "close": texts[1],
                "change_rate": texts[3],
                "total_value": f"{total_value_million:,}",
                "individual": f"{individual_val:+,}",
                "institution": texts[5],
                "foreign": texts[6],
            })
            if len(result) >= days:
                break
    except Exception as e:
        print(f"[DEBUG] {code} 수급동향 조회 중 예외: {e}")
    return result

# ─────────────────────────────────────────────────────────────
# 3-2. 주가 동향 코멘트 (수급 패턴 분석 + 뉴스 스크랩)
# ─────────────────────────────────────────────────────────────
def fetch_stock_news(code: str, count: int = 10) -> list:
    """종목별 뉴스 헤드라인 스크랩 (finance.naver.com/item/news_news.naver)"""
    url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
    result = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', class_='type5')
        if not table:
            return result
        for row in table.find_all('tr'):
            title_el = row.select_one('td.title a')
            date_el = row.select_one('td.date')
            if not title_el or not date_el:
                continue
            title = title_el.get_text(strip=True)
            date_txt = date_el.get_text(strip=True)  # 'YYYY.MM.DD HH:MM'
            if title:
                result.append({"title": title, "date": date_txt})
            if len(result) >= count:
                break
    except Exception as e:
        print(f"[DEBUG] {code} 뉴스 조회 중 예외: {e}")
    return result

def fetch_trade_status(code: str) -> dict:
    """
    실시간 거래정지 여부 확인 (polling.finance.naver.com 개별 종목 API의 tradeStopType).
    marketStatus는 장 시작 전(PREOPEN)엔 모든 종목이 동일하게 나오므로 정지 여부
    판단에 쓰면 안 되고, tradeStopType.name이 'HALTED'인지로만 판단해야 정확하다
    (정상 거래 종목은 장 시작 전에도 'TRADING'으로 나옴 — 실제로 유진기업/삼성전자로 대조 확인).
    """
    url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        d = r.json()['datas'][0]
        stop = d.get('tradeStopType') or {}
        return {"halted": stop.get('name') == 'HALTED', "text": stop.get('text', '')}
    except Exception as e:
        print(f"[DEBUG] {code} 거래상태 조회 중 예외: {e}")
        return {"halted": False, "text": ""}

def fetch_stock_notices(code: str, count: int = 5) -> list:
    """
    종목 공시 헤드라인 스크랩 (finance.naver.com/item/news_notice.naver).
    KRX/KOSCOM이 낸 공시(매매거래정지, 단기과열종목 지정 등)가 그대로 올라오므로
    거래정지 사유를 추정하는 근거로 쓴다. KRX Open API나 DART 없이도 확인 가능.
    """
    url = f"https://finance.naver.com/item/news_notice.naver?code={code}&page=1"
    result = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', class_='type6')
        if not table:
            return result
        for row in table.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            if len(cells) < 3:
                continue
            title = cells[0].get_text(strip=True)
            date_txt = cells[2].get_text(strip=True)
            if title and title != '제목':
                result.append({"title": title, "date": date_txt})
            if len(result) >= count:
                break
    except Exception as e:
        print(f"[DEBUG] {code} 공시 조회 중 예외: {e}")
    return result

def _find_streak(history: list, key: str):
    """history는 최신일이 [0]인 리스트. 가장 최근일부터 같은 부호(순매수/순매도)가
    끊기지 않고 이어지는 길이를 센다. 0(거래 없음)을 만나면 스트릭이 끊긴 것으로 본다."""
    sign, length = None, 0
    for h in history:
        v = _parse_signed_int(h[key])
        if v == 0:
            break
        s = 1 if v > 0 else -1
        if sign is None:
            sign, length = s, 1
        elif s == sign:
            length += 1
        else:
            break
    return sign, length

def _find_zero_volume_streak(history: list) -> int:
    length = 0
    for h in history:
        if h.get('total_value') == '0':
            length += 1
        else:
            break
    return length

CORP_SUFFIXES = ['기업', '그룹', '증권', '홀딩스', '시멘트', '산업', '건설', '로보틱스']

def _company_root(name: str) -> str:
    """
    회사명에서 흔한 법인 접미사를 뗀 '핵심 이름'을 구한다.
    예: '유진기업' -> '유진' (그러면 '유진그룹'을 다룬 기사도 관련 기사로 인정됨).
    '동양'처럼 접미사가 안 붙는 짧은 이름은 그대로 반환된다 — 다만 '동양'은 그
    자체로 흔한 낱말이라, 제목에 이 낱말이 있다고 무조건 관련 기사는 아닐 수 있음
    (예: '동양' 관련이 아니라 옛 '동양그룹' 시절 이슈를 다룬 기사 등). 그래서
    이 함수는 "완전히 무관한 기사"를 걸러내는 최소한의 필터로만 쓴다.
    """
    for suf in CORP_SUFFIXES:
        if name.endswith(suf) and len(name) > len(suf):
            return name[:-len(suf)]
    return name

def _match_news(news_list: list, date_str: str, display_name: str):
    """
    date_str('YYYY.MM.DD') 당일 뉴스 중 종목명(또는 그 핵심 이름)이 제목에 들어간
    것만 매칭한다. 같은 날짜에 이 코드로 태그된 기사가 있어도 제목에 회사명이 아예
    없으면(예: 과거 계열사 시절 이슈 등 실제로는 무관한 기사) 매칭하지 않는다.
    여러 건이면 이름이 제목 앞쪽에 나오는 기사를 우선한다
    (예: "유진기업, 장 초반 15% 급등…" 같은 단독 기사가 "…혼조…유진기업·KBI메탈…"
    같은 여러 종목 나열형 리스트 기사보다 실제 원인을 설명할 가능성이 높음).
    """
    root = _company_root(display_name)
    same_day = [n for n in news_list if n['date'].startswith(date_str)]
    named = [n for n in same_day if root in n['title']]
    if not named:
        return None
    named.sort(key=lambda n: n['title'].find(root))
    return named[0]

def _find_related_news(news_list: list, date_str: str, display_name: str, window_days: int = 3):
    """같은 날 매칭이 없으면, date_str 이전 window_days일 내에서도 회사명이 제목에
    들어간 기사가 있는지 찾는다 (이름이 없는 기사는 여기서도 매칭하지 않는다)."""
    matched = _match_news(news_list, date_str, display_name)
    if matched:
        return matched
    try:
        target = datetime.strptime(date_str, '%Y.%m.%d')
    except Exception:
        return None
    root = _company_root(display_name)
    for n in news_list:  # news_list는 최신순
        if root not in n['title']:
            continue
        try:
            n_date = datetime.strptime(n['date'][:10], '%Y.%m.%d')
        except Exception:
            continue
        if 0 <= (target - n_date).days <= window_days:
            return n
    return None

def fetch_daily_ohlc(code: str, count: int = 12) -> list:
    """일별 시가/고가/저가/종가/거래량을 시간순(오래된→최신)으로 반환 (fchart XML)"""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
    rows = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'xml')
        for item in soup.find_all('item'):
            parts = item.get('data', '').split('|')
            if len(parts) < 6:
                continue
            d_str, o, h, l, c, v = parts[:6]
            try:
                rows.append({
                    "date": f"{d_str[:4]}.{d_str[4:6]}.{d_str[6:8]}",
                    "open": int(o), "high": int(h), "low": int(l),
                    "close": int(c), "volume": int(v),
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[DEBUG] {code} 일별 OHLC 조회 중 예외: {e}")
    return rows  # fchart는 이미 시간순으로 내려줌

def _flow_summary_sentence(h: dict, price_up: bool = None) -> str:
    """해당일의 개인(추정)/기관/외국인 순매매를 매수측·매도측으로 나눠 원인 설명 문장으로 요약"""
    inst_v = _parse_signed_int(h['institution'])
    for_v = _parse_signed_int(h['foreign'])
    ind_v = _parse_signed_int(h['individual'])
    flows = [('개인', ind_v), ('기관', inst_v), ('외국인', for_v)]
    buyers = sorted([f for f in flows if f[1] > 0], key=lambda x: -x[1])
    sellers = sorted([f for f in flows if f[1] < 0], key=lambda x: x[1])

    if buyers and sellers:
        top_nm, top_v = buyers[0]
        sell_txt = '·'.join(f"{nm}({v:+,}주)" for nm, v in sellers)
        return f"수급 측면에서는 {top_nm}이 {top_v:+,}주 순매수한 반면 {sell_txt}이 순매도하며 엇갈린 모습을 보였다"
    if buyers:
        buy_txt = '·'.join(f"{nm}({v:+,}주)" for nm, v in buyers)
        verb = '상승을 뒷받침한' if price_up else '수급을 지지한'
        return f"수급 측면에서는 {buy_txt}이 순매수 우위를 보이며 {verb} 것으로 풀이된다"
    if sellers:
        sell_txt = '·'.join(f"{nm}({v:+,}주)" for nm, v in sellers)
        verb = '하락 압력으로 작용한' if price_up is False else '수급 부담으로 작용한'
        return f"수급 측면에서는 {sell_txt}이 순매도 우위를 보이며 {verb} 것으로 풀이된다"
    return ''

def _last_trading_day_index(ohlc_asc: list):
    """시간순(오래된→최신) 리스트에서 거래량이 있는 가장 최근 날짜의 인덱스 (비교할 전일이 있어야 하므로 index>=1)"""
    for i in range(len(ohlc_asc) - 1, 0, -1):
        if ohlc_asc[i]['volume'] > 0:
            return i
    return None

def _describe_latest_trading_day(code: str, display_name: str, ohlc_asc: list, hist_by_date: dict, news: list) -> str:
    """
    가장 최근 실제 거래일 하루를 '시가 → (장중 급변동 있었다면) 고점/저점 → 종가' 흐름과
    그날의 수급 우위, 관련 뉴스까지 묶어 한 문단으로 서술. 변동폭 크기와 무관하게 항상 생성.
    """
    idx = _last_trading_day_index(ohlc_asc)
    if idx is None:
        return ''
    day = ohlc_asc[idx]
    prev_close = ohlc_asc[idx - 1]['close']
    if not prev_close:
        return ''

    # 장중(당일 실시간)인지 확인 — 아직 안 끝난 하루를 "종가...마감"이라고 부르면
    # 이미 끝난 것처럼 오해하게 되므로 문구를 다르게 처리한다.
    is_live_today = (day['date'] == datetime.now().strftime('%Y.%m.%d')) and is_krx_open()

    open_pct = (day['open'] - prev_close) / prev_close * 100
    high_pct = (day['high'] - prev_close) / prev_close * 100
    low_pct = (day['low'] - prev_close) / prev_close * 100
    close_pct = (day['close'] - prev_close) / prev_close * 100

    if open_pct >= 3:
        open_desc = f"장 초반부터 상승세로 출발(시가 {day['open']:,}원, {open_pct:+.1f}%)"
    elif open_pct <= -3:
        open_desc = f"장 초반부터 하락세로 출발(시가 {day['open']:,}원, {open_pct:+.1f}%)"
    else:
        open_desc = f"시가 {day['open']:,}원으로 출발"

    # 장중 고점/저점이 종가(또는 현재가)보다 훨씬 튀면(되돌림이 있었으면) 그 흐름을 덧붙임
    peak_pct, direction = (high_pct, 'up') if abs(high_pct) >= abs(low_pct) else (low_pct, 'down')
    mid_desc = ''
    if abs(peak_pct - close_pct) >= 6.0:
        if direction == 'up':
            mid_desc = f", 장중 한때 {day['high']:,}원까지 상승({peak_pct:+.1f}%)했으나 상승분을 상당 부분 반납"
        else:
            mid_desc = f", 장중 한때 {day['low']:,}원까지 하락({peak_pct:+.1f}%)했으나 낙폭을 일부 만회"

    if is_live_today:
        close_desc = f"현재가(장중) {day['close']:,}원({close_pct:+.2f}%)"
    else:
        close_desc = f"종가 {day['close']:,}원({close_pct:+.2f}%)에 마감"
    parts = [f"{day['date']} {open_desc}{mid_desc}, {close_desc}"]

    h = hist_by_date.get(day['date'])
    if h:
        flow_sentence = _flow_summary_sentence(h, price_up=(close_pct > 0) if close_pct != 0 else None)
        if flow_sentence:
            parts.append(flow_sentence)
    elif is_live_today:
        # 네이버 수급 데이터(frgn.naver)는 장마감 후에야 당일 행이 채워지므로,
        # 장중엔 오늘자 기관/외국인 순매매를 아직 알 수 없다 — 조용히 생략하는 대신
        # 왜 없는지 명시해서 "수급 원인 없음"으로 오해하지 않게 한다.
        parts.append("당일 기관·외국인 수급은 장마감 후 집계되어 아직 반영되지 않음")

    matched = _find_related_news(news, day['date'], display_name)
    if matched:
        parts.append(f"관련 기사 「{matched['title']}」({matched['date']})")
    else:
        parts.append("최근 관련 뉴스는 확인되지 않음")

    return '. '.join(parts)

# ─────────────────────────────────────────────────────────────
# 3-3. DART(전자공시) 연동 — 거래정지 등의 '진짜' 사유를 구조화된 공시
# 원문에서 직접 읽어온다 (네이버 공시 게시판은 제목만 있고 본문 링크가
# KIND/DART로 넘어가는 JS 리다이렉트라 본문을 못 읽어옴 — DART Open API로
# 원문 문서를 직접 받아야 함)
# ─────────────────────────────────────────────────────────────
DART_CORP_CODES = {
    "001520": "00117337",  # 동양 — DART 고유번호(종목코드와 다름)
    "023410": "00184667",  # 유진기업
    "001200": "00131054",  # 유진투자증권
    "040300": "00200275",  # YTN
    "484810": "01458161",  # 티엑스알로보틱스
    "300720": "01319808",  # 한일시멘트
    "004980": "00132804",  # 성신양회
    "038500": "00239639",  # 삼표시멘트
    "183190": "00990165",  # 아세아시멘트
    "198440": "01032583",  # 강동씨앤엘
}

def fetch_dart_disclosures(corp_code: str, bgn_de: str, end_de: str) -> list:
    """DART 공시 목록 (list.json) — bgn_de/end_de는 'YYYYMMDD', 최신순 반환"""
    if not DART_API_KEY:
        return []
    try:
        r = requests.get("https://opendart.fss.or.kr/api/list.json", params={
            "crtfc_key": DART_API_KEY, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de, "page_no": 1, "page_count": 100,
        }, timeout=15)
        data = r.json()
        if data.get('status') != '000':  # '013'=조회된 데이터 없음 등은 정상 케이스
            return []
        return data.get('list', [])
    except Exception as e:
        print(f"[DEBUG] DART 공시목록({corp_code}) 조회 중 예외: {e}")
        return []

def fetch_dart_document_text(rcept_no: str) -> str:
    """DART 공시 원문(document.xml, zip으로 내려옴)을 텍스트로 반환"""
    if not DART_API_KEY:
        return ''
    try:
        r = requests.get("https://opendart.fss.or.kr/api/document.xml", params={
            "crtfc_key": DART_API_KEY, "rcept_no": rcept_no,
        }, timeout=15)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            raw = z.read(z.namelist()[0])
        for enc in ('utf-8', 'euc-kr', 'cp949'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='replace')
    except Exception as e:
        print(f"[DEBUG] DART 문서({rcept_no}) 조회 중 예외: {e}")
        return ''

_dart_capital_cache = {}  # {종목코드: 억원 단위 자본금(int) 또는 None} — 서버 실행 중 재사용

def fetch_dart_capital(code: str):
    """
    DART 재무제표(개별, 최근 사업보고서)에서 재무상태표 '자본금' 계정을 조회해
    억원 단위(반올림)로 반환. 액면가·우선주 유무에 따라 종목마다 계산식이 달라
    수동으로 정확히 맞추기 어려웠는데, 이건 회사가 직접 공시한 실측값이라 정확하다.
    DART_API_KEY가 없거나 조회 실패 시 None (호출부에서 하드코딩 폴백 사용).
    """
    if code in _dart_capital_cache:
        return _dart_capital_cache[code]

    corp_code = DART_CORP_CODES.get(code)
    if not corp_code or not DART_API_KEY:
        return None

    this_year = datetime.now().year
    # 연초에는 직전 연도 사업보고서가 아직 안 나왔을 수 있어 최대 2개 연도 재시도
    for year in (this_year - 1, this_year - 2):
        try:
            r = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": corp_code,
                "bsns_year": str(year), "reprt_code": "11011", "fs_div": "OFS",
            }, timeout=15)
            data = r.json()
            if data.get('status') != '000':
                continue
            for item in data.get('list', []):
                if item.get('sj_div') == 'BS' and item.get('account_nm', '').strip() == '자본금':
                    capital_billion = round(int(item['thstrm_amount']) / 100_000_000)
                    _dart_capital_cache[code] = capital_billion
                    return capital_billion
        except Exception as e:
            print(f"[DEBUG] {code} DART 자본금 조회 중 예외({year}): {e}")

    _dart_capital_cache[code] = None
    return None

def _extract_date_range_section(html_text: str, section_label: str):
    """
    DART 표준 서식 문서에서 rowspan으로 묶인 '~기간' 섹션(예: 매매거래정지기간)의
    시작일/종료일을 순서대로 찾아 반환한다. 표 구조: 첫 행엔 [섹션라벨, '시작일', 값],
    다음 행엔 [(라벨 생략), '종료일', 값] — 그래서 섹션라벨이 나온 바로 다음 '종료일'
    행까지만 본다.
    """
    soup = BeautifulSoup(html_text, 'html.parser')
    start_date = end_date = None
    capture_next = False
    for row in soup.find_all('tr'):
        texts = [c.get_text(strip=True) for c in row.find_all('td')]
        if not texts:
            continue
        value_span = row.find('span', class_='xforms_input')
        val = value_span.get_text(strip=True) if value_span else ''
        if texts[0] == section_label:
            start_date = val if val and val != '-' else None
            capture_next = True
            continue
        if capture_next:
            if texts[0] == '종료일':
                end_date = val if val and val != '-' else None
            capture_next = False
    return start_date, end_date

def fetch_dart_halt_info(code: str):
    """
    최근 60일 내 '주식병합결정'/'주식소각결정' 공시가 있으면 원문을 읽어
    매매거래정지기간(시작/종료)까지 뽑아온다. DART_API_KEY가 없거나 해당
    공시가 없으면 None (호출부에서 다른 방식으로 폴백).
    """
    corp_code = DART_CORP_CODES.get(code)
    if not corp_code or not DART_API_KEY:
        return None
    end_de = datetime.now().strftime('%Y%m%d')
    bgn_de = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')
    disclosures = fetch_dart_disclosures(corp_code, bgn_de, end_de)

    target = None
    for keyword in ('주식병합결정', '주식소각결정'):
        target = next((d for d in disclosures if keyword in d.get('report_nm', '')), None)
        if target:
            break
    if not target:
        return None

    reason_name = re.sub(r'\s+', ' ', target['report_nm']).strip()
    rcept_dt = target.get('rcept_dt', '')
    date_fmt = f"{rcept_dt[:4]}.{rcept_dt[4:6]}.{rcept_dt[6:8]}" if len(rcept_dt) == 8 else rcept_dt

    doc_text = fetch_dart_document_text(target['rcept_no'])
    if not doc_text:
        return {"reason": reason_name, "start": None, "end": None, "date": date_fmt}

    start, end = _extract_date_range_section(doc_text, '매매거래정지기간')
    return {"reason": reason_name, "start": start, "end": end, "date": date_fmt}

# ─────────────────────────────────────────────────────────────
# 3-3-2. 단판공시(단일판매ㆍ공급계약체결) 모니터링 — 동양(주)이 낸 개별 공사
# 수주/공급계약 공시를 원문에서 파싱해 "현재 진행 중인(만기 미도래) 현장"만
# 추려서 표로 보여준다. 같은 현장이라도 계약금액 증액/기간연장이 생기면
# [기재정정] 공시가 계속 이어지는데, 원문 하단 '※ 관련공시' 링크에 그 현장의
# 이전 공시 rcpno가 전부 들어있어서 이걸로 같은 현장 공시들을 하나로 묶는다.
# (해지된 계약이 섞인 묶음은 통째로 제외 — 더 이상 진행 중인 현장이 아니므로.)
# ─────────────────────────────────────────────────────────────
DANPAN_TARGET_STOCK_CODE = "001520"  # 동양(주) — 건설부문 단판공시 모니터링 대상
DANPAN_REPORT_KEYWORDS = ('단일판매', '공급계약')
DANPAN_LOOKBACK_YEARS = 10  # 공사기간이 보통 1~5년이라 이 정도면 진행 중인 현장은 다 잡힘
DANPAN_CACHE_TTL = 6 * 3600  # 초 — 원문을 수십 건씩 새로 받아오는 무거운 작업이라 캐시

def _danpan_parse_document(html_text: str) -> dict:
    """단일판매ㆍ공급계약체결/정정/해지 공시 원문에서 라벨을 매칭해 핵심 필드를
    뽑는다. [기재정정] 문서에도 본문 표는 항상 정정 반영 후 '현재' 값으로 들어있어서,
    정정 전/후 비교표는 볼 필요가 없다.

    표의 HTML id(XFormD1/XFormD8/XFormD14...)는 공시 작성 시점의 DART 서식 버전에
    따라 달라서 id로 찾지 않는다 — 대신 "체결계약명"/"해지계약명"(또는 오래된
    자율공시 서식에서 쓰는 "세부내용") 라벨이 있는 표를 찾는다. [기재정정] 문서는
    본문 표 앞에 "정정 전/후" 비교표가 먼저 나오는데, 계약명이 정정 대상이면 그
    비교표에도 우연히 같은 라벨이 걸릴 수 있어 문서에 여러 개 걸리면 문서 뒤쪽에
    나오는(=본문) 표를 쓴다."""
    soup = BeautifulSoup(html_text, 'html.parser')
    table = None
    for t in soup.find_all('table'):
        for row in t.find_all('tr'):
            tds = row.find_all('td')
            if not tds:
                continue
            label = ' '.join(td.get_text(strip=True) for td in tds[:-1])
            if '체결계약명' in label or '해지계약명' in label or '세부내용' in label:
                table = t  # 계속 덮어써서 마지막(=본문) 매치를 사용
                break
    if not table:
        return {}
    result = {'related_rcept_nos': []}
    for row in table.find_all('tr'):
        tds = row.find_all('td')
        if not tds:
            continue
        label = ' '.join(td.get_text(strip=True) for td in tds[:-1])
        value_td = tds[-1]
        value = value_td.get_text(strip=True)
        if '체결계약명' in label or '해지계약명' in label or '세부내용' in label:
            result['contract_name'] = value
            result['is_termination'] = '해지계약명' in label
        elif '계약금액' in label or '해지금액' in label:
            result['amount'] = _danpan_parse_won(value)
        elif '시작일' in label:
            result['period_start'] = value if value and value != '-' else None
        elif '종료일' in label:
            result['period_end'] = value if value and value != '-' else None
        elif '계약상대' in label and '관계' not in label:
            result['counterparty'] = value
        elif '계약' in label and '수주' in label and '일' in label:
            result['contract_date'] = value
        elif '해지일자' in label:
            result['contract_date'] = value
        elif '관련공시' in label:
            for a in value_td.find_all('a', href=True):
                m = re.search(r'rcpno=(\d+)', a['href'])
                if m:
                    result['related_rcept_nos'].append(m.group(1))
    return result

def _danpan_parse_won(text: str):
    text = text.replace(',', '').strip()
    if not text or text == '-':
        return None
    try:
        return int(text)
    except ValueError:
        return None

def _dots(date_str):
    """"2026-07-13" → "2026.07.13" — 공시 탭(단판공시ㆍ지분공시) 화면에 나가는
    날짜는 전부 이 점(.) 구분 표기로 통일한다. None/빈 문자열/형식이 다른 값은
    그대로 둔다."""
    if not date_str:
        return date_str
    return date_str.replace('-', '.') if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str) else date_str

_periodic_report_cache = {}  # {corp_code: {'ts': float, 'rcept_no', 'rcept_dt', 'text'}}
PERIODIC_REPORT_CACHE_TTL = 6 * 3600

def _fetch_latest_periodic_report(corp_code: str, force: bool = False):
    """가장 최근의 "온전한"(정정본 아닌) 사업/반기/분기보고서 원문을 찾아 반환한다.
    단판공시·지분공시 두 기능이 똑같이 "최근 정기보고서 한 건"을 필요로 해서 공용으로
    뺐다 — 두 기능을 같이 열어도 같은 정기보고서를 두 번 받아오지 않는다.
    반환값: (rcept_no, rcept_dt, 원문 text) 또는 실패 시 (None, None, None).
    """
    now = datetime.now().timestamp()
    cached = _periodic_report_cache.get(corp_code)
    if not force and cached and now - cached['ts'] < PERIODIC_REPORT_CACHE_TTL:
        return cached['rcept_no'], cached['rcept_dt'], cached['text']

    end_de = datetime.now().strftime('%Y%m%d')
    bgn_de = (datetime.now() - timedelta(days=400)).strftime('%Y%m%d')
    try:
        r = requests.get("https://opendart.fss.or.kr/api/list.json", params={
            "crtfc_key": DART_API_KEY, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de, "pblntf_ty": "A",
            "page_no": 1, "page_count": 20,
        }, timeout=15)
        data = r.json()
    except Exception as e:
        print(f"[DEBUG] 정기보고서 목록 조회 중 예외: {e}")
        return None, None, None
    if data.get('status') != '000':
        return None, None, None

    # [기재정정]은 정정된 항목만 담고 있어 전체 표가 없을 수 있으므로 제외하고
    # 가장 최근 "온전한" 정기보고서를 쓴다.
    candidates = [d for d in data.get('list', [])
                  if not d.get('report_nm', '').startswith('[기재정정]')
                  and any(k in d.get('report_nm', '') for k in ('사업보고서', '반기보고서', '분기보고서'))]
    if not candidates:
        return None, None, None
    candidates.sort(key=lambda d: d.get('rcept_dt', ''), reverse=True)
    latest = candidates[0]

    text = fetch_dart_document_text(latest['rcept_no'])
    if not text:
        return None, None, None

    _periodic_report_cache[corp_code] = {
        'ts': now, 'rcept_no': latest['rcept_no'], 'rcept_dt': latest.get('rcept_dt', ''), 'text': text,
    }
    return latest['rcept_no'], latest.get('rcept_dt', ''), text

def _danpan_fetch_periodic_progress(corp_code: str):
    """가장 최근 정기보고서의 "그 밖에 투자자 보호를 위하여 필요한 사항 > 1. 공시내용
    진행 및 변경사항 > 나. 단일판매ㆍ공급계약체결공시에 대한 진행 현황" 표를 파싱한다.

    이 표는 회사가 매 정기보고서마다 "현재 관리 중인 단판공시 현장"만 골라서
    신고일자(최초) 기준으로 나열한 것이라, 공사기간 종료일이 지났는지 여부보다
    훨씬 정확한 "아직 진행 중인가"의 근거가 된다 — 공사기간이 연장돼도 별도
    정정공시를 안 내는 경우가 많아 종료일만으로는 이미 끝난 현장을 걸러낼 수
    없기 때문. 반환값은 (기준일 date, {신고일자(최초) 'YYYY-MM-DD', ...} set).
    조회/파싱에 실패하면 (None, None) — 호출부는 이 경우 종료일 기반 판단으로
    폴백해야 한다.
    """
    _, _, text = _fetch_latest_periodic_report(corp_code)
    if not text:
        return None, None

    soup = BeautifulSoup(text, 'html.parser')
    title_tag = next(
        (p for p in soup.find_all('p') if '단일판매' in p.get_text() and '진행 현황' in p.get_text()),
        None,
    )
    if not title_tag:
        return None, None

    tables = title_tag.find_all_next('table')
    if len(tables) < 2:
        return None, None

    base_date = None
    m = re.search(r'(\d{4})년\s*(\d{2})월\s*(\d{2})일', tables[0].get_text())
    if m:
        base_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    reported_dates = set()
    for row in tables[1].find_all('tr'):
        cells = row.find_all('td')
        if not cells:
            continue
        first = cells[0].get_text(strip=True)
        if re.match(r'^\d{4}-\d{2}-\d{2}$', first):
            reported_dates.add(first)

    return base_date, reported_dates

_annual_financials_cache = {}  # {(corp_code, bsns_year_or_None): {'ts': float, 'data': ...}}
ANNUAL_FINANCIALS_CACHE_TTL = 24 * 3600

def _fetch_annual_financials(corp_code: str, bsns_year: int = None):
    """단일판매ㆍ공급계약체결 공시의무 기준(유가증권시장 공시규정 제7조제1항제1호다목:
    최근 사업연도 매출액의 5%, 대규모법인은 2.5%)을 계산하기 위해 특정 사업연도의
    연결 매출액ㆍ자산총계를 가져온다. 자산총계 2조원 이상이면 대규모법인으로 보고
    2.5% 기준을 적용한다. `bsns_year`를 안 주면(=지금 "규정 보기" 모달 용도) 올해
    기준 "최근 사업연도"를 자동으로 찾고, 특정 연도를 주면(=사전검증 계산기 용도)
    그 연도만 조회한다. 조회 실패 시 None."""
    now = datetime.now().timestamp()
    cache_key = (corp_code, bsns_year)
    cached = _annual_financials_cache.get(cache_key)
    if cached and now - cached['ts'] < ANNUAL_FINANCIALS_CACHE_TTL:
        return cached['data']

    if bsns_year is not None:
        years_to_try = [bsns_year]
    else:
        this_year = datetime.now().year
        years_to_try = [this_year - 1, this_year - 2]

    for year in years_to_try:
        try:
            r = requests.get("https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": corp_code,
                "bsns_year": str(year), "reprt_code": "11011", "fs_div": "CFS",
            }, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[DEBUG] {corp_code} 연결 매출액/자산총계 조회 중 예외({year}): {e}")
            continue
        if data.get('status') != '000':
            continue

        revenue = assets = None
        for item in data.get('list', []):
            name = item.get('account_nm', '').strip()
            try:
                if item.get('sj_div') == 'IS' and name in ('매출액', '수익(매출액)') and revenue is None:
                    revenue = int(item['thstrm_amount'])
                elif item.get('sj_div') == 'BS' and name == '자산총계' and assets is None:
                    assets = int(item['thstrm_amount'])
            except (ValueError, KeyError):
                continue

        if revenue is not None:
            is_large_corp = bool(assets and assets >= 2_000_000_000_000)  # 자산총액 2조원 이상
            threshold_pct = 0.025 if is_large_corp else 0.05
            result = {
                "fiscal_year": year,
                "revenue": revenue,
                "assets": assets,
                "is_large_corp": is_large_corp,
                "threshold_pct": threshold_pct,
                "threshold_amount": round(revenue * threshold_pct),
            }
            _annual_financials_cache[cache_key] = {'ts': now, 'data': result}
            return result

    return None

def _resolve_fiscal_year_asof(corp_code: str, as_of_date):
    """계약일자(as_of_date) 시점에 실제로 이미 DART에 제출돼있던 가장 최근
    "사업보고서"(반기ㆍ분기보고서 제외 — "최근 사업연도"는 연간 결산 기준)를 찾아
    그 사업연도를 반환한다. 예: 2023-06-02에 계약을 맺었다면, 그 시점에 최근
    제출된 사업보고서가 "사업보고서 (2022.12)"였는지 확인해 2022를 반환 — 지금
    시점(2026년)의 "최근 사업연도"가 아니라, **계약 당시** 실제로 참조 가능했던
    매출액 기준을 재현하기 위함이다. 회사는 2021년부터 이어져 온 단판공시 현장을
    지금도 관리하고 있어서, 오래된 계약을 사후 검증하려면 이 시점 보정이 필요하다.
    반환값: (사업연도:int, report_nm, rcept_dt) 또는 실패 시 (None, None, None)."""
    end_de = as_of_date.strftime('%Y%m%d')
    bgn_de = (as_of_date - timedelta(days=800)).strftime('%Y%m%d')  # 사업보고서는 매년 1건 → 2년 넉넉히
    try:
        r = requests.get("https://opendart.fss.or.kr/api/list.json", params={
            "crtfc_key": DART_API_KEY, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de, "pblntf_ty": "A",
            "page_no": 1, "page_count": 20,
        }, timeout=15)
        data = r.json()
    except Exception as e:
        print(f"[DEBUG] {corp_code} 사업보고서 목록 조회 중 예외: {e}")
        return None, None, None
    if data.get('status') != '000':
        return None, None, None

    # 반기ㆍ분기보고서는 "사업연도" 확정 기준이 아니므로 제외, [기재정정]은 원본과
    # 사업연도가 같으므로 어느 쪽이 걸려도 무방하지만 원본을 우선한다.
    candidates = [
        d for d in data.get('list', [])
        if re.match(r'^(\[기재정정\])?사업보고서', d.get('report_nm', ''))
        and d.get('rcept_dt', '') <= end_de
    ]
    if not candidates:
        return None, None, None
    candidates.sort(key=lambda d: (d.get('rcept_dt', ''), not d.get('report_nm', '').startswith('[')))
    latest = candidates[-1]
    m = re.search(r'\((\d{4})\.\d{2}\)', latest.get('report_nm', ''))
    if not m:
        return None, None, None
    return int(m.group(1)), latest.get('report_nm', '').strip(), latest.get('rcept_dt', '')

def check_danpan_disclosure(contract_date_str: str, amount: int):
    """단판공시 사전검증 — 계약(예정)일자와 계약금액을 받아, **그 계약일자 시점에
    실제로 적용됐을 "최근 사업연도" 매출액 기준**으로 공시대상 여부를 판단한다.
    (지금 시점 기준 최신 매출액이 아니라 계약일자 당시 매출액을 쓰는 이유는 위
    _resolve_fiscal_year_asof 설명 참고.) 실패 시 None."""
    corp_code = DART_CORP_CODES.get(DANPAN_TARGET_STOCK_CODE)
    if not corp_code or not DART_API_KEY:
        return None
    try:
        contract_date = datetime.strptime(contract_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

    fiscal_year, report_nm, rcept_dt = _resolve_fiscal_year_asof(corp_code, contract_date)
    if fiscal_year is None:
        return None

    financials = _fetch_annual_financials(corp_code, bsns_year=fiscal_year)
    if not financials:
        return None

    return {
        "contract_date": _dots(contract_date_str),
        "applicable_fiscal_year": fiscal_year,
        "applicable_report_nm": report_nm,
        "applicable_report_date": _dots(f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}") if len(rcept_dt) == 8 else rcept_dt,
        "revenue": financials["revenue"],
        "assets": financials["assets"],
        "is_large_corp": financials["is_large_corp"],
        "threshold_pct": financials["threshold_pct"],
        "threshold_amount": financials["threshold_amount"],
        "amount": amount,
        "is_disclosure_required": amount >= financials["threshold_amount"],
    }

_danpan_cache = {'ts': 0.0, 'data': None, 'meta': None}

def fetch_danpan_monitoring(force: bool = False) -> list:
    """정기보고서의 진행현황 표(우선) 또는 공사기간 종료일(폴백)로 판단해,
    아직 관리 중인 단판공시 현장 목록을 반환. DART_API_KEY가 없으면 빈 리스트."""
    now = datetime.now().timestamp()
    if not force and _danpan_cache['data'] is not None and now - _danpan_cache['ts'] < DANPAN_CACHE_TTL:
        return _danpan_cache['data']

    corp_code = DART_CORP_CODES.get(DANPAN_TARGET_STOCK_CODE)
    if not corp_code or not DART_API_KEY:
        return []

    periodic_base_date, periodic_dates = _danpan_fetch_periodic_progress(corp_code)

    end_de = datetime.now().strftime('%Y%m%d')
    bgn_de = (datetime.now() - timedelta(days=365 * DANPAN_LOOKBACK_YEARS)).strftime('%Y%m%d')

    all_items = []
    page = 1
    while True:
        try:
            r = requests.get("https://opendart.fss.or.kr/api/list.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": corp_code,
                "bgn_de": bgn_de, "end_de": end_de, "page_no": page, "page_count": 100,
            }, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[DEBUG] 단판공시 목록 조회 중 예외(page={page}): {e}")
            break
        if data.get('status') != '000':
            break
        all_items.extend(data.get('list', []))
        if page >= int(data.get('total_page', 1) or 1):
            break
        page += 1

    targets = [d for d in all_items
               if all(k in d.get('report_nm', '') for k in DANPAN_REPORT_KEYWORDS)]

    docs = {}
    for item in targets:
        rcept_no = item['rcept_no']
        text = fetch_dart_document_text(rcept_no)
        if not text:
            continue
        parsed = _danpan_parse_document(text)
        if not parsed.get('contract_name'):
            continue
        parsed['rcept_no'] = rcept_no
        parsed['rcept_dt'] = item.get('rcept_dt', '')
        docs[rcept_no] = parsed

    # union-find: '※ 관련공시' 링크로 이어진 문서들을 같은 현장 묶음으로 클러스터링
    parent = {rn: rn for rn in docs}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    # ※ 관련공시 링크의 rcpno는 KRX(KIND) 자체 접수번호라 DART API의 rcept_no와
    # 자릿수 체계가 달라서 값을 그대로 비교하면 매칭되지 않는다 (같은 공시인데 예:
    # KRX 20220224000460 ↔ DART 20220224800460 — 날짜 8자리는 같고, 뒤 6자리
    # 일련번호의 첫 글자만 다르다). 코스피 상장사는 이 규칙(앞자리를 '8'로
    # 치환)이 일관되게 성립해 이걸로 직접 변환해 매칭한다. 혹시 규칙이 안 맞는
    # 예외가 있을 때만 같은 날짜에 접수된 단판공시가 정확히 1건일 경우에 한해
    # 날짜로 폴백한다 (같은 날 서로 다른 두 현장 공시가 겹치면 오매칭 위험이
    # 있어 후보가 여럿이면 연결하지 않는다).
    date_index = {}
    for rn, d in docs.items():
        date_index.setdefault(d['rcept_dt'], []).append(rn)
    for rn, d in docs.items():
        for rel in d.get('related_rcept_nos', []):
            cand = None
            if len(rel) == 14:
                guess = rel[:8] + '8' + rel[9:]
                if guess in docs:
                    cand = guess
            if cand is None:
                same_day = date_index.get(rel[:8], [])
                if len(same_day) == 1:
                    cand = same_day[0]
            if cand and cand != rn:
                union(rn, cand)

    clusters = {}
    for rn in docs:
        clusters.setdefault(find(rn), []).append(rn)

    today = datetime.now().date()
    results = []
    for members in clusters.values():
        items = sorted((docs[m] for m in members), key=lambda d: (d['rcept_dt'], d['rcept_no']))
        if any(d.get('is_termination') for d in items):
            continue  # 해지된 계약 묶음은 통째로 제외

        earliest, latest = items[0], items[-1]
        rcept_dt = earliest.get('rcept_dt', '')
        earliest_date_fmt = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}" if len(rcept_dt) == 8 else None
        earliest_date_obj = None
        if earliest_date_fmt:
            try:
                earliest_date_obj = datetime.strptime(earliest_date_fmt, '%Y-%m-%d').date()
            except ValueError:
                pass

        # 정기보고서 기준일 이전에 최초 신고된 현장이면 그 정기보고서의 진행현황
        # 표가 이 현장을 다뤘어야 정상이다 — 표에 없으면 "더 이상 관리되지 않는
        # 현장"(준공/종료됐지만 별도 정정·해지 공시는 안 낸 경우)으로 보고 제외한다.
        # 정기보고서 기준일 이후에 새로 신고된 현장은 아직 그 표에 반영될 수 없으므로
        # (아래) 공사기간 종료일 기준으로만 판단한다.
        checked_by_periodic = bool(
            periodic_dates is not None and periodic_base_date and earliest_date_obj
            and earliest_date_obj <= periodic_base_date
        )
        if checked_by_periodic:
            if earliest_date_fmt not in periodic_dates:
                continue  # 정기보고서 진행현황에 더 이상 없음 → 관리 종료로 판단, 제외
        else:
            period_end = latest.get('period_end')
            if period_end:
                try:
                    if datetime.strptime(period_end, '%Y-%m-%d').date() < today:
                        continue  # 정기보고서로 아직 확인 불가한 신규 건 → 종료일로 판단
                except ValueError:
                    pass

        initial_amount = earliest.get('amount')
        current_amount = latest.get('amount')
        change_rate = (
            (current_amount - initial_amount) / initial_amount
            if initial_amount and current_amount is not None else None
        )
        latest_rcept_dt = latest.get('rcept_dt', '')
        latest_dt_fmt = f"{latest_rcept_dt[:4]}.{latest_rcept_dt[4:6]}.{latest_rcept_dt[6:8]}" if len(latest_rcept_dt) == 8 else latest_rcept_dt

        results.append({
            "site_name": latest.get('contract_name'),
            "counterparty": latest.get('counterparty'),
            "initial_contract_date": _dots(earliest.get('contract_date')),
            "latest_disclosure_date": latest_dt_fmt,
            "amount": current_amount,
            "initial_amount": initial_amount,
            "change_rate": change_rate,
            "period_start": _dots(latest.get('period_start')),
            "period_end": _dots(latest.get('period_end')),
            "revision_count": len(items) - 1,
            "rcept_no": latest['rcept_no'],
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={latest['rcept_no']}",
            "checked_by_periodic_report": checked_by_periodic,
        })

    results.sort(key=lambda r: (r['period_end'] is None, r['period_end'] or ''))
    meta = {
        "periodic_report_base_date": periodic_base_date.isoformat() if periodic_base_date else None,
        "periodic_check_available": periodic_dates is not None,
        "disclosure_rule": _fetch_annual_financials(corp_code),
    }
    _danpan_cache.update(ts=now, data=results, meta=meta)
    return results

# ─────────────────────────────────────────────────────────────
# 3-3-3. 지분공시(임원ㆍ주요주주 소유상황보고서) 모니터링 — 동전주 이슈로 임원들이
# 매월 자사주를 사들이는 걸 팀에서 사람이 직접 취합하고 있었는데, 이걸 DART
# Open API로 자동화한다. "임원ㆍ주요주주 특정증권등 소유상황보고서"는 임원/주요
# 주주 본인이 지분 변동 시마다 개별적으로 제출하는 공시라 corp_code로 조회하면
# 동양(주)과 관련된 소유상황보고서가 전부 걸린다(제출자=flr_nm은 회사가 아니라
# 그 개인/법인 이름).
# ─────────────────────────────────────────────────────────────
EQUITY_REPORT_NAME = '임원ㆍ주요주주특정증권등소유상황보고서'
EQUITY_LOOKBACK_YEARS = 10
EQUITY_CACHE_TTL = 6 * 3600

def _equity_parse_num(text: str):
    """"50,000" 같은 보통 형식뿐 아니라, 오래된 서식에서 보이는 "1,961(원)"처럼
    뒤에 단위가 붙은 값도 앞의 숫자만 뽑아 처리한다."""
    text = text.strip()
    if not text or text == '-':
        return None
    m = re.match(r'-?[\d,]+', text)
    if not m:
        return None
    try:
        return int(m.group(0).replace(',', ''))
    except ValueError:
        return None

def _equity_is_buy(t: dict) -> bool:
    """"매수 이력"으로 집계할 거래인지 판단한다. 보고사유 텍스트에 "매수"가 들어간
    "장내매수(+)"/"장외매수(+)" 외에도, "시간외매매(+)"나 "제3자배정유상증자(+)"처럼
    문구엔 "매수"가 없지만 실질은 유상 취득인 사유들이 있어서(유진기업의
    2026-06-24 시간외매매 800,000주 취득이 "매수"라는 단어가 없어 누락됐던 게
    실제 사례) 사유 텍스트로 화이트리스트를 만드는 대신 "수량이 늘었고(qty>0)
    단가가 있다(price is not None)"로 판단한다. 무상증자ㆍ주식병합ㆍ상속ㆍ증여처럼
    대가 없이 수량만 바뀌는 사유는 취득/처분단가란이 항상 "-"(파싱하면 None)라
    이 조합으로 자연스럽게 제외된다."""
    return bool(t.get('qty') and t['qty'] > 0 and t.get('price') is not None)

def _equity_parse_document(html_text: str) -> dict:
    """임원ㆍ주요주주 특정증권등 소유상황보고서 원문을 파싱한다. 단판공시 문서와
    달리 이 서식은 값마다 ACODE(고정값)/AUNIT(선택값, aunitvalue에 코드)가 직접
    붙어있는 표준 서식이라 라벨 텍스트 매칭 대신 이 속성으로 바로 찾는다(개인
    보고자든 유진기업 같은 법인 보고자든 태그 구조는 동일)."""
    soup = BeautifulSoup(html_text, 'html.parser')
    name_tag = soup.find(attrs={'acode': 'IFR_NM'})
    if not name_tag:
        return {}
    name = name_tag.get_text(strip=True)

    reg_tag = soup.find(attrs={'aunit': 'STF_RYN'})          # 임원 등기여부 (예: 등기임원/비등기임원/-)
    position_tag = soup.find(attrs={'acode': 'STF_PSM'})     # 직위명
    mainsh_tag = soup.find(attrs={'aunit': 'MAIN_SH'})       # 주요주주 여부 (값이 있으면 "-"가 아님)

    # 정확성 추적 대상 3개 필드 — 매 보고서마다 실려 있어 문서 간 대조가 가능하다.
    #   1) 임원 선임일(STF_APT_DT): 같은 사람이면 어느 보고서를 봐도 같은 값이어야 함
    #   2) 발행주식총수(FLT_SUM): 회사 전체 값이라 비슷한 시기 보고서끼리 같아야 함
    #   3) 주식 수(BFR/AFR/MDF_PS_CPT_CNT): "직전보고서"+"증감"="이번보고서" 산식이
    #      맞아야 하고, 이 보고서의 AFR이 다음 보고서의 BFR과 이어져야 함
    apt_dt_tag = soup.find(attrs={'aunit': 'STF_APT_DT'})
    flt_sum_tag = soup.find(attrs={'acode': 'FLT_SUM'})
    report_type_tag = soup.find(attrs={'aunit': 'RPT_DST'})  # 보고구분: 신규/변동 — 요청서류 판단에 씀
    bfr_cnt_tag = soup.find(attrs={'acode': 'BFR_PS_CPT_CNT'})
    afr_cnt_tag = soup.find(attrs={'acode': 'AFR_PS_CPT_CNT'})
    mdf_cnt_tag = soup.find(attrs={'acode': 'MDF_PS_CPT_CNT'})

    def _apt_date(tag):
        val = tag.attrs.get('aunitvalue') if tag else None
        if not val or val == '-' or len(val) != 8:
            return None
        return f"{val[:4]}-{val[4:6]}-{val[6:8]}"

    # "다. 세부변동내역" 표: 행마다 RPT_RSN(보고사유, 예: 장내매수(+)/시간외매매(+)/
    # 제3자배정유상증자(+)/주식병합 등)이 있다. 두 가지를 걸러야 한다:
    # - 증권종류(STR_KND)가 보통주(코드 "1")가 아닌 행은 건너뛴다. 유진기업처럼
    #   보통주ㆍ우선주를 모두 보유한 보고자는 한 공시 안에 두 증권종류가 각각 별도
    #   행으로 나오는데(예: 2026-07-07 주식병합 공시가 보통주 행 하나, 우선주 행
    #   하나), 이 필드를 안 보고 "마지막 행"만 가져오면 우선주 수량이 보통주
    #   누적수량을 덮어써버린다. 이 기능은 동전주(보통주) 이슈를 보려는 것이라
    #   우선주는 애초에 대상이 아니다.
    # - 증가 거래인지는 사유 텍스트를 "매수"로 문자열 매칭하지 않는다. "시간외매매(+)"
    #   나 "제3자배정유상증자(+)"처럼 실질적으로는 매수와 같은 유상 취득인데 "매수"라는
    #   단어가 안 들어간 사유가 있어서(유진기업의 800,000주 시간외매매 건이 이렇게
    #   빠졌었음) 대신 "수량이 늘었고(qty>0) 단가가 있다(price is not None)"로
    #   판단한다 — 무상증자ㆍ주식병합ㆍ상속ㆍ증여처럼 대가 없이 수량만 바뀌는 사유는
    #   단가란이 항상 "-"(None)라 이 조합으로 자연스럽게 걸러진다.
    transactions = []
    for reason_tag in soup.find_all(attrs={'aunit': 'RPT_RSN'}):
        row = reason_tag.find_parent('tr')
        if not row:
            continue
        kind_tag = row.find(attrs={'aunit': 'STR_KND'})
        if kind_tag and kind_tag.attrs.get('aunitvalue') != '1':
            continue  # 보통주(1)가 아닌 행(우선주 등)은 건너뜀
        date_tag = row.find(attrs={'aunit': 'MDF_DM'})
        qty_tag = row.find(attrs={'acode': 'MDF_STK_CNT'})
        price_tag = row.find(attrs={'acode': 'ACI_AMT2'})
        after_tag = row.find(attrs={'acode': 'AFR_STK_CNT'})
        date_val = date_tag.attrs.get('aunitvalue') if date_tag else None
        qty = _equity_parse_num(qty_tag.get_text(strip=True)) if qty_tag else None
        if not date_val or len(date_val) != 8 or qty is None:
            continue
        transactions.append({
            'reason': reason_tag.get_text(strip=True),
            'date': f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:8]}",
            'qty': qty,
            'price': _equity_parse_num(price_tag.get_text(strip=True)) if price_tag else None,
            'after_qty': _equity_parse_num(after_tag.get_text(strip=True)) if after_tag else None,
        })

    # 이 보고서 기준 "현재 보유 총수량"은 표 맨 마지막 거래 행의 변동후(AFR_STK_CNT)를
    # 쓴다. 처음엔 "합계" 행의 AFR_STK_SUM을 썼는데, 실제로 받아보니 그 값은 거래가
    # 1건뿐인 보고서에서만 채워지고 여러 건이면 "-"로 비워두는 서식이라(정진학의
    # 2026-06-10 보고서처럼 매수가 2건이면 합계 행 변동후가 "-") 그 경우 결과가
    # None이 돼버렸다. 개별 거래 행의 변동후는 거래 건수와 무관하게 항상 채워져
    # 있어서 이걸로 바꿨다(표는 항상 날짜 오름차순으로 기재되므로 마지막 행 = 최신).
    final_holding = transactions[-1]['after_qty'] if transactions else None

    return {
        'name': name,
        'registered_text': reg_tag.get_text(strip=True) if reg_tag else '',
        'position': position_tag.get_text(strip=True) if position_tag else '',
        'is_major_shareholder': bool(mainsh_tag and mainsh_tag.get_text(strip=True) not in ('', '-')),
        'transactions': transactions,
        'final_holding': final_holding,
        'appointment_date': _apt_date(apt_dt_tag),
        'issued_shares_total': _equity_parse_num(flt_sum_tag.get_text(strip=True)) if flt_sum_tag else None,
        'bfr_qty': _equity_parse_num(bfr_cnt_tag.get_text(strip=True)) if bfr_cnt_tag else None,
        'afr_qty': _equity_parse_num(afr_cnt_tag.get_text(strip=True)) if afr_cnt_tag else None,
        'mdf_qty': _equity_parse_num(mdf_cnt_tag.get_text(strip=True)) if mdf_cnt_tag else None,
        'report_type': report_type_tag.get_text(strip=True) if report_type_tag else '',
    }

# 지분공시 준비에 필요한 증빙서류 — 보고구분(report_type)별로 다르다.
EQUITY_REQUIRED_DOCS = {
    '신규': ['임원 선임서(임원 명령서)', '매매거래내역증빙', '잔고증명서'],
    '변동': ['매매거래내역서', '잔고증명서'],
}

def _equity_parse_post_base_date_officer_changes(soup):
    """"임원 현황" 본표는 정기보고서 "작성기준일" 시점의 스냅샷이라, 그 이후 실제로
    발생한 임원 변동(퇴임ㆍ신규선임)은 본표 바로 아래 "* 보고서 작성기준일 이후
    퇴임현황" / "* 보고서 작성기준일 이후 신규 선임현황"이라는 안내문과 함께 별도
    표로 붙는다(예: 2026.05.15 분기보고서 — 작성기준일 자체는 2026.03.31이지만,
    보고서를 실제 제출한 5월 15일 시점에 이미 알려진 3월 말 퇴임ㆍ5월 초 신규선임
    까지 반영해 이 두 표에 적어둠). 본표와 달리 이 두 표는 ACODE/AUNIT 없는
    순수 HTML 표라 라벨 텍스트로 표를 찾고 컬럼 순서로 값을 읽는다.
    반환: (퇴임자 이름 집합, 신규 선임자 {성명: {position, reg_type}} dict).
    둘 다 해당 안내문 자체가 없으면(그 분기에 변동이 없었으면) 빈 값을 반환한다."""
    retired = set()
    retire_marker = soup.find(string=re.compile('퇴임현황'))
    if retire_marker:
        table = retire_marker.find_next('table')
        if table:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'te'])
                if len(cells) < 2:
                    continue
                name = cells[1].get_text(strip=True)  # 구분(0) / 성명(1) / 직위(2) / 등기임원 여부(3) / 발령일자(4)
                if name and name != '성명':
                    retired.add(name)

    new_hires = {}
    hire_marker = soup.find(string=re.compile(r'신규\s*선임현황'))
    if hire_marker:
        table = hire_marker.find_next('table')
        if table:
            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'te'])
                if len(cells) < 5:
                    continue
                name = cells[0].get_text(strip=True)  # 성명(0)/성별(1)/출생년월(2)/직위(3)/등기임원여부(4)/...
                if not name or name == '성명':
                    continue
                new_hires[name] = {
                    'position': cells[3].get_text(strip=True),
                    'reg_type': cells[4].get_text(strip=True),
                }
    return retired, new_hires

def _equity_fetch_officer_roster(corp_code: str):
    """가장 최근 정기보고서의 "VIII. 임원 및 직원 등에 관한 사항 > 1. 임원 및 직원
    등의 현황 > 가. 임원 현황" 표에서 현재 재직 중인 임원의 직위ㆍ등기구분을 뽑아온다
    ({성명: {'position': 직위명, 'reg_type': '사내이사'|'사외이사'|'미등기'}}).
    지분공시 이력에서 이 표에 없는 사람(퇴임한 임원)은 걸러내는 기준으로 쓰인다 —
    주요주주(법인 등)는 애초에 이 표 대상이 아니므로 걸러내지 않는다. 정기보고서
    조회 자체에 실패하면 잘못 걸러내는 걸 막기 위해 None을 반환한다(호출부는 이
    경우 필터링을 건너뛰어야 함).

    같은 표 앞쪽에 "최대주주 및 특수관계인" 등 다른 표에서도 우연히 같은
    ACODE="SH5_NM_T"가 붙은 행이 섞여 나오는데, 그 행들은 등기구분(SH5_REG_DRCT)이
    없어서 자동으로 걸러진다 — 등기구분이 있는 행만 채택한다.

    이 본표는 "작성기준일" 시점 스냅샷이라, 실제 사용자 사례(김종택 전무)처럼 본표에는
    아직 남아있지만 보고서 제출 시점에는 이미 퇴임 처리된 경우가 있다. 그래서 본표를
    읽은 뒤 _equity_parse_post_base_date_officer_changes()로 "작성기준일 이후
    퇴임현황"/"신규 선임현황" 표를 마저 반영해 최종 roster를 보정한다."""
    _, _, text = _fetch_latest_periodic_report(corp_code)
    if not text:
        return None
    soup = BeautifulSoup(text, 'html.parser')
    roster = {}
    for name_tag in soup.find_all(attrs={'acode': 'SH5_NM_T'}):
        row = name_tag.find_parent('tr')
        if not row:
            continue
        name = name_tag.get_text(strip=True)
        if not name:
            continue
        regdrct_tag = row.find(attrs={'aunit': 'SH5_REG_DRCT'})
        if not regdrct_tag:
            continue  # 임원 현황 표가 아닌 다른 표에서 우연히 걸린 행 — 무시
        position_tag = row.find(attrs={'acode': 'SH5_LEV'})
        roster[name] = {
            'position': position_tag.get_text(strip=True) if position_tag else '',
            'reg_type': regdrct_tag.get_text(strip=True),  # 사내이사/사외이사/미등기
        }

    retired, new_hires = _equity_parse_post_base_date_officer_changes(soup)
    for name in retired:
        roster.pop(name, None)
    roster.update(new_hires)  # 신규 선임자가 본표에 없던 이름이면 추가, 있었으면 최신 정보로 덮어씀
    return roster

def _equity_fmt8(d: str) -> str:
    return f"{d[:4]}.{d[4:6]}.{d[6:8]}" if d and len(d) == 8 else (d or '')

def _equity_compute_accuracy(by_person: dict) -> dict:
    """지분공시에서 실제로 오기재가 잦다고 알려진 3개 필드 — 임원 선임일ㆍ
    발행주식총수ㆍ주식 수 — 를 보고서 간에 대조해 불일치 후보를 찾는다. 자동으로
    고치는 게 아니라 사람이 다시 확인해야 할 목록을 추려주는 용도(오탐 가능성이
    있으므로 "이상 없음"이 아니라 "확인 필요"로 취급할 것)."""
    officer_issues = []
    share_count_issues = []
    issued_shares_points = []  # (rcept_dt, rcept_no, holder_name, value)

    for name, docs in by_person.items():
        docs = sorted(docs, key=lambda d: (d['rcept_dt'], d['rcept_no']))

        # 1) 임원 선임일 — 같은 사람의 모든 보고서에 적힌 값이 하나여야 함
        apt_dates = {}
        for d in docs:
            v = d['parsed'].get('appointment_date')
            if v:
                apt_dates.setdefault(v, []).append(d['rcept_no'])
        if len(apt_dates) > 1:
            officer_issues.append({
                "holder_name": name,
                "detail": f"보고서마다 선임일이 다르게 기재됨: {', '.join(apt_dates.keys())}",
                "variants": [{"value": v, "rcept_nos": nos} for v, nos in apt_dates.items()],
            })

        # 2) 주식 수 — 문서 내 "직전+증감=이번" 산식, 그리고 이 보고서의 "이번보고서"
        #    수량이 다음 보고서의 "직전보고서" 수량과 이어져야 함
        prev_afr, prev_rcept = None, None
        for d in docs:
            p = d['parsed']
            bfr, afr, mdf = p.get('bfr_qty'), p.get('afr_qty'), p.get('mdf_qty')
            if bfr is not None and afr is not None and mdf is not None:
                if bfr + mdf != afr and bfr - mdf != afr:
                    share_count_issues.append({
                        "holder_name": name,
                        "detail": f"{d['rcept_no']}: 직전보고서({bfr:,})+증감({mdf:,})이 이번보고서({afr:,})와 맞지 않음",
                        "rcept_no": d['rcept_no'],
                    })
            if prev_afr is not None and bfr is not None and bfr != prev_afr:
                share_count_issues.append({
                    "holder_name": name,
                    "detail": f"{prev_rcept}의 이번보고서 수량({prev_afr:,})과 {d['rcept_no']}의 직전보고서 수량({bfr:,})이 이어지지 않음",
                    "rcept_no": d['rcept_no'],
                })
            if afr is not None:
                prev_afr, prev_rcept = afr, d['rcept_no']

        # 3) 발행주식총수 — 회사 전체 공통값이라 시점별로 하나여야 함(타임라인으로 노출)
        for d in docs:
            v = d['parsed'].get('issued_shares_total')
            if v is not None:
                issued_shares_points.append((d['rcept_dt'], d['rcept_no'], name, v))

    issued_shares_points.sort(key=lambda t: (t[0], t[1]))
    timeline = []
    by_date = {}
    for rcept_dt, rcept_no, name, v in issued_shares_points:
        by_date.setdefault(rcept_dt, set()).add(v)
        if not timeline or timeline[-1]['value'] != v:
            timeline.append({"date": _equity_fmt8(rcept_dt), "value": v, "rcept_no": rcept_no})
    same_day_conflicts = [
        {"date": _equity_fmt8(rcept_dt), "values": sorted(values)}
        for rcept_dt, values in by_date.items() if len(values) > 1
    ]
    current_value = issued_shares_points[-1][3] if issued_shares_points else None

    return {
        "issued_shares_total": {
            "current_value": current_value,
            "timeline": timeline,
            "same_day_conflicts": same_day_conflicts,
        },
        "officer_appointment_issues": officer_issues,
        "share_count_issues": share_count_issues,
    }

_equity_cache = {'ts': 0.0, 'data': None, 'meta': None}

def fetch_equity_monitoring(force: bool = False) -> list:
    """최근 10년간 임원ㆍ주요주주 소유상황보고서를 스캔해 주주(임원/주요주주)별
    매수 이력(최초/최근 매수일, 누적 매수량, 평균단가)을 집계한다. 매도ㆍ증여ㆍ
    주식병합 등 매수가 아닌 사유는 집계에서 제외한다. DART_API_KEY가 없으면
    빈 리스트."""
    now = datetime.now().timestamp()
    if not force and _equity_cache['data'] is not None and now - _equity_cache['ts'] < EQUITY_CACHE_TTL:
        return _equity_cache['data']

    corp_code = DART_CORP_CODES.get(DANPAN_TARGET_STOCK_CODE)
    if not corp_code or not DART_API_KEY:
        return []

    roster = _equity_fetch_officer_roster(corp_code)  # None이면 정기보고서 조회 실패 → 퇴임자 필터링 건너뜀

    end_de = datetime.now().strftime('%Y%m%d')
    bgn_de = (datetime.now() - timedelta(days=365 * EQUITY_LOOKBACK_YEARS)).strftime('%Y%m%d')

    all_items = []
    page = 1
    while True:
        try:
            r = requests.get("https://opendart.fss.or.kr/api/list.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": corp_code,
                "bgn_de": bgn_de, "end_de": end_de, "pblntf_ty": "D",
                "page_no": page, "page_count": 100,
            }, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[DEBUG] 지분공시 목록 조회 중 예외(page={page}): {e}")
            break
        if data.get('status') != '000':
            break
        all_items.extend(data.get('list', []))
        if page >= int(data.get('total_page', 1) or 1):
            break
        page += 1

    # 정정본은 이미 제출된 보고서의 오기재를 바로잡는 것뿐이라 새 거래내역이
    # 아니므로 뺀다 — 원본 보고서만으로 매수 이력을 집계한다.
    targets = [d for d in all_items if d.get('report_nm', '') == EQUITY_REPORT_NAME]

    by_person = {}
    for item in targets:
        rcept_no = item['rcept_no']
        text = fetch_dart_document_text(rcept_no)
        if not text:
            continue
        parsed = _equity_parse_document(text)
        name = parsed.get('name')
        if not name:
            continue
        by_person.setdefault(name, []).append({
            'rcept_no': rcept_no, 'rcept_dt': item.get('rcept_dt', ''), 'parsed': parsed,
        })

    results = []
    for name, docs in by_person.items():
        docs.sort(key=lambda d: (d['rcept_dt'], d['rcept_no']))
        buy_txns = [
            (d['rcept_dt'], d['rcept_no'], t['date'], t['qty'], t['price'])
            for d in docs for t in d['parsed']['transactions']
            if _equity_is_buy(t)
        ]
        if not buy_txns:
            continue  # 매수 이력이 없으면(매도ㆍ증여ㆍ병합 등만 있으면) 이 표에서는 제외

        buy_txns.sort(key=lambda t: t[2])  # 실제 매매(변동)일 기준 정렬
        first_date = buy_txns[0][2]

        # "최근 매수일(공시일)"ㆍ원문은 매수 거래가 포함된 공시 중 가장 최근 것을 기준으로
        latest_doc = max(
            (d for d in docs if any(_equity_is_buy(t) for t in d['parsed']['transactions'])),
            key=lambda d: (d['rcept_dt'], d['rcept_no']),
        )
        latest_rcept_dt = latest_doc['rcept_dt']
        latest_dt_fmt = f"{latest_rcept_dt[:4]}.{latest_rcept_dt[4:6]}.{latest_rcept_dt[6:8]}" if len(latest_rcept_dt) == 8 else latest_rcept_dt

        # "누적 주식수" = 가장 최근 공시(전체 중 최신, 매수 공시가 아니어도 됨)의
        # 최종 보유수량(final_holding) — 그 시점의 확정된 총 보유수량이다. 매수
        # 거래만 다시 더해서 계산하면 증여ㆍ주식병합 등으로 실제 보유수량과
        # 어긋나거나, 보고서마다 "누적"이 아니라 "그 회차 변동분"만 적힌 경우도
        # 있어 값이 들쭉날쭉해지는 문제가 있었다.
        total_qty = None
        for d in reversed(docs):
            if d['parsed'].get('final_holding') is not None:
                total_qty = d['parsed']['final_holding']
                break
        if total_qty is None:
            total_qty = sum(t[3] for t in buy_txns)  # 폴백: 파싱 실패 시 매수 합계라도

        priced = [t for t in buy_txns if t[4] is not None]
        avg_price = (sum(t[3] * t[4] for t in priced) / sum(t[3] for t in priced)) if priced else None

        last_parsed = docs[-1]['parsed']  # 가장 최근 공시에 적힌 신상정보(직위 등)를 채택
        is_major_shareholder = last_parsed.get('is_major_shareholder', False)

        # 현재 정기보고서의 임원 현황에 없는 사람은 퇴임한 임원 — 주요주주(법인 등)는
        # 이 표(임원 현황)에 애초에 안 잡히는 별개 카테고리라 걸러내지 않는다.
        # roster가 None이면 정기보고서 조회 자체가 실패한 것이라 필터링을 건너뛴다
        # (안 그러면 조회 실패 시 전원이 "퇴임자"로 잘못 걸러짐).
        if roster is not None and not is_major_shareholder and name not in roster:
            continue

        roster_entry = (roster or {}).get(name) or {}
        if is_major_shareholder:
            role_label = '최대주주'
        else:
            # 정기보고서 임원현황의 등기구분("사내이사"/"사외이사"/"미등기")을 우선 쓰고,
            # 그 표에 없는 예외적인 경우에만 공시 원문 자체의 등기임원여부로 대체한다.
            role_label = roster_entry.get('reg_type') or ('등기' if '등기임원' in (last_parsed.get('registered_text') or '') else '미등기')

        # "유진기업 주식회사" 같은 "OO 주식회사" 표기를 팀에서 익숙한 "OO(주)"로 정리
        display_name = name[:-5] + '(주)' if name.endswith(' 주식회사') else name

        # 요청서류 — 이 사람의 가장 최근 공시 건(전체 중 최신, 매수 공시가 아니어도 됨)이
        # "신규"(첫 소유상황보고)인지 "변동"(그 이후 보고)인지에 따라 요청할 증빙이 다르다.
        latest_report_type = docs[-1]['parsed'].get('report_type') or ''
        required_documents = EQUITY_REQUIRED_DOCS.get(latest_report_type, EQUITY_REQUIRED_DOCS['변동'])

        results.append({
            "holder_name": display_name,
            "role_label": role_label,
            "position": roster_entry.get('position') or last_parsed.get('position') or '',
            "registered_text": last_parsed.get('registered_text') or '',
            "is_major_shareholder": is_major_shareholder,
            "first_buy_date": _dots(first_date),
            "latest_buy_date": latest_dt_fmt,
            "total_qty": total_qty,
            "avg_price": round(avg_price, 1) if avg_price is not None else None,
            "disclosure_count": len(docs),
            "rcept_no": latest_doc['rcept_no'],
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={latest_doc['rcept_no']}",
            "latest_report_type": latest_report_type,
            "latest_rcept_no": docs[-1]['rcept_no'],
            "required_documents": required_documents,
        })

    results.sort(key=lambda r: r['holder_name'])  # 가나다순
    meta = {
        "officer_roster_available": roster is not None,
        "lookback_years": EQUITY_LOOKBACK_YEARS,
    }
    accuracy = _equity_compute_accuracy(by_person)
    _equity_cache.update(ts=now, data=results, meta=meta, accuracy=accuracy)
    return results

# ─────────────────────────────────────────────────────────────
# 3-3-4. 지분공시 — 주식등의 대량보유상황보고서("5% Rule") 모니터링. 임원ㆍ주요주주
# 소유상황보고서와 달리 이건 발행주식의 5% 이상을 보유하게 된 자(및 그 이후 1%p
# 이상 변동 시, 자본시장법 제147조)가 본인뿐 아니라 특별관계자(계열회사ㆍ공동
# 보유자ㆍ임원 등)까지 하나의 문서로 "연명보고"한다 — 그래서 공시 1건 안에
# "보고자 및 특별관계자별 보유내역" 표로 여러 명의 보유수량이 함께 신고된다.
# 조회 기준(10년 lookback, corp_code 목록 조회 방식)은 지분공시(임원ㆍ주요주주)와
# 동일하게 맞춘다.
# ─────────────────────────────────────────────────────────────
LARGE_HOLDING_REPORT_KEYWORD = '대량보유'
LARGE_HOLDING_LOOKBACK_YEARS = EQUITY_LOOKBACK_YEARS
LARGE_HOLDING_CACHE_TTL = EQUITY_CACHE_TTL

def _lh_clean(text: str) -> str:
    """DART 문서의 셀 안 줄바꿈이 "&cr;"라는 자체 마커로 그대로 남아있는 경우가
    있어(정식 HTML 엔티티가 아니라 BeautifulSoup이 디코딩하지 못함, 예:
    "특별&cr;관계자") 텍스트 추출 후 항상 이걸 제거해야 한다."""
    return (text or '').replace('&cr;', '').replace('&cr', '').strip()

def _lh_normalize_name(name: str) -> str:
    """같은 법인인데 공시마다 "(주)삼표기초소재"(접두)ㆍ"삼표기초소재(주)"(접미)
    처럼 "(주)" 표기 위치가 뒤섞여 나와서, 정규화 없이 이름을 그대로 집계 키로
    쓰면 동일 법인이 서로 다른 두 행으로 쪼개진다("(주)삼표기초소재" 행은 특정
    공시에서 우연히 보유주식수가 "-"(0)로만 나온 반면, "삼표기초소재(주)" 행에는
    실제 수치가 잡혀 실체는 하나인데 표에는 둘로 보였음). "OO(주)" 접미 표기로
    통일한다."""
    name = name.strip()
    if name.startswith('(주)'):
        return name[3:].strip() + '(주)'
    if name.endswith(' 주식회사'):
        return name[:-5].strip() + '(주)'
    return name

def _lh_parse_ratio(text: str):
    """지분율(예: "23.68", "0.00")은 소수점까지 살려야 한다 — 정수 파싱용
    _equity_parse_num을 쓰면 "23.68"이 정수부만 남아 "23"이 돼버린다."""
    text = (text or '').strip()
    if not text or text == '-':
        return None
    m = re.match(r'-?[\d,]+(\.\d+)?', text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(',', ''))
    except ValueError:
        return None

def _large_holding_parse_document(html_text: str) -> list:
    """주식등의 대량보유상황보고서(일반/약식) 원문에서 "보고자 및 특별관계자별
    보유내역"("1. 보고자 및 특별관계자별 보유내역 > 가. 주식등의 종류별 보유내역",
    ACLASS="CST_CNT1")을 뽑는다. 보고자 1행 + 특별관계자 N행(관계 컬럼이 세로로
    병합된 TD라 값이 있는 행이 나올 때마다 갱신해가며 다음 행들에 적용해야 함)으로,
    각 행에 성명(SPC_NM)ㆍ보유주식합계(STK_CNT)ㆍ비율(STK_RT)이 있다 — 이게 실제
    "누가 몇 주 들고 있는지"의 근거.

    구분(classification)은 딱 두 갈래다:
    - 보고자 본인: 표지의 FLT_CRP_RLT(발행회사와의 관계)가 문자 그대로 "최대주주"면
      그대로 "최대주주"로 쓴다. 그렇지 않으면(예: "주주") 이 보고자 그룹 전체(보고자+
      특별관계자 합산) 보유비율인 SUM_TMT_RT를 기준으로 10% 이상이면 "10%이상주주",
      5% 이상이면 "5%이상주주"로 판단한다 — 개별 보고자의 FLT_CRP_RLT 텍스트는
      "최대주주"만 명시적으로 나오고 5%/10%대 문구는 나오지 않는 경우가 있어서,
      대량보유상황보고서 제도 자체의 기준(5%/10%)을 직접 적용한다.
    - 그 외(특별관계자, 법인ㆍ개인 불문): 전부 "특별관계자"로 단순 표기한다.

    반환하는 각 행에는 이 문서의 관계="보고자" 행 이름(reporter_name, 연명보고의
    대표 보고자)도 함께 붙는다 — 화면에서는 표를 순번이 아니라 이 보고자명으로
    묶어서 보여준다."""
    soup = BeautifulSoup(html_text, 'html.parser')

    top_relation_tag = soup.find(attrs={'aunit': 'FLT_CRP_RLT'})
    top_relation = _lh_clean(top_relation_tag.get_text(strip=True)) if top_relation_tag else ''
    group_ratio_tag = soup.find(attrs={'acode': 'SUM_TMT_RT'})
    group_ratio = _lh_parse_ratio(group_ratio_tag.get_text(strip=True)) if group_ratio_tag else None

    if top_relation == '최대주주':
        reporter_classification = '최대주주'
    elif group_ratio is not None and group_ratio >= 10:
        reporter_classification = '10%이상주주'
    elif group_ratio is not None and group_ratio >= 5:
        reporter_classification = '5%이상주주'
    else:
        reporter_classification = top_relation or '보고자'

    holdings_group = soup.find('table-group', attrs={'aclass': 'CST_CNT1'})
    entries = []
    if holdings_group:
        current_relation = ''
        for row in holdings_group.find_all('tr'):
            relation_td = row.find('td')
            if relation_td and _lh_clean(relation_td.get_text(strip=True)):
                current_relation = _lh_clean(relation_td.get_text(strip=True))  # "보고자" / "특별관계자"
            name_tag = row.find(attrs={'acode': 'SPC_NM'})
            qty_tag = row.find(attrs={'acode': 'STK_CNT'})
            ratio_tag = row.find(attrs={'acode': 'STK_RT'})
            if not name_tag or not qty_tag:
                continue
            name = _lh_normalize_name(_lh_clean(name_tag.get_text(strip=True)))
            qty = _equity_parse_num(qty_tag.get_text(strip=True))
            if not name or qty is None:
                continue
            classification = reporter_classification if current_relation == '보고자' else '특별관계자'
            entries.append({
                'name': name,
                'relation': current_relation,
                'classification': classification,
                'qty': qty,
                'ratio': _lh_parse_ratio(ratio_tag.get_text(strip=True)) if ratio_tag else None,
            })

    # "보고자명"(연명보고의 대표 보고자) — 이 문서의 관계="보고자" 행 이름을 모든
    # 행(보고자 본인 포함)에 함께 붙여준다. 화면에서는 순번 대신 이 값으로 묶어서 본다.
    reporter_name = next((e['name'] for e in entries if e['relation'] == '보고자'), None)
    for e in entries:
        e['reporter_name'] = reporter_name
    return entries

_large_holding_cache = {'ts': 0.0, 'data': None, 'meta': None}

def fetch_large_holding_monitoring(force: bool = False) -> list:
    """최근 10년간 주식등의 대량보유상황보고서를 스캔해, 보고서마다 함께 연명
    신고되는 "보고자 및 특별관계자별 보유내역"을 신고자(보고자 본인 + 특별관계자)
    단위로 펼쳐 집계한다. 같은 사람/법인이 여러 회차에 걸쳐 등장하면 최초로 등장한
    공시일을 "최초 공시일", 가장 최근 등장한 공시일을 "변동 공시일"로, 가장 최근
    등장한 회차의 보유수량을 "누적 주식수"로 잡는다."""
    now = datetime.now().timestamp()
    if not force and _large_holding_cache['data'] is not None and now - _large_holding_cache['ts'] < LARGE_HOLDING_CACHE_TTL:
        return _large_holding_cache['data']

    corp_code = DART_CORP_CODES.get(DANPAN_TARGET_STOCK_CODE)
    if not corp_code or not DART_API_KEY:
        return []

    end_de = datetime.now().strftime('%Y%m%d')
    bgn_de = (datetime.now() - timedelta(days=365 * LARGE_HOLDING_LOOKBACK_YEARS)).strftime('%Y%m%d')

    all_items = []
    page = 1
    while True:
        try:
            r = requests.get("https://opendart.fss.or.kr/api/list.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": corp_code,
                "bgn_de": bgn_de, "end_de": end_de, "pblntf_ty": "D",
                "page_no": page, "page_count": 100,
            }, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[DEBUG] 대량보유상황보고서 목록 조회 중 예외(page={page}): {e}")
            break
        if data.get('status') != '000':
            break
        all_items.extend(data.get('list', []))
        if page >= int(data.get('total_page', 1) or 1):
            break
        page += 1

    # 정정본은 이미 제출된 보고서의 오기재를 바로잡는 것뿐이라 새 보유내역이
    # 아니므로 뺀다 — 원본(일반/약식) 보고서만으로 집계한다.
    targets = [
        d for d in all_items
        if LARGE_HOLDING_REPORT_KEYWORD in d.get('report_nm', '') and '정정' not in d.get('report_nm', '')
    ]
    targets.sort(key=lambda d: (d.get('rcept_dt', ''), d.get('rcept_no', '')))

    by_entity = {}  # name -> {first_date, last_date, qty, ratio, classification, reporter_name, rcept_no}
    for item in targets:
        rcept_no = item['rcept_no']
        rcept_dt = item.get('rcept_dt', '')
        text = fetch_dart_document_text(rcept_no)
        if not text:
            continue
        date_fmt = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}" if len(rcept_dt) == 8 else rcept_dt
        for entry in _large_holding_parse_document(text):
            name = entry['name']
            existing = by_entity.get(name)
            if existing is None:
                by_entity[name] = {
                    'first_date': date_fmt,
                    'last_date': date_fmt,
                    'qty': entry['qty'],
                    'ratio': entry['ratio'],
                    'classification': entry['classification'],
                    'reporter_name': entry['reporter_name'],
                    'rcept_no': rcept_no,
                }
            else:
                existing['first_date'] = min(existing['first_date'], date_fmt)
                if date_fmt >= existing['last_date']:
                    existing['last_date'] = date_fmt
                    existing['qty'] = entry['qty']
                    existing['ratio'] = entry['ratio']
                    existing['classification'] = entry['classification']
                    existing['reporter_name'] = entry['reporter_name']
                    existing['rcept_no'] = rcept_no

    results = []
    for name, v in by_entity.items():
        if not v['qty']:
            continue  # 가장 최근 등장한 회차의 보유수량이 0(완전 처분ㆍ서식상 "-")이면 현재는 보유자가 아니므로 제외
        results.append({
            "reporter_name": v['reporter_name'] or name,
            "holder_name": name,
            "role_label": v['classification'],
            "first_disclosure_date": _dots(v['first_date']),
            "latest_disclosure_date": _dots(v['last_date']),
            "total_qty": v['qty'],
            "ratio": v['ratio'],
            "rcept_no": v['rcept_no'],
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={v['rcept_no']}",
        })

    # 보고자명(연명보고 그룹) 가나다순으로 묶고, 같은 그룹 안에서는 보고자 본인이
    # 먼저 오도록(신고자==보고자명), 그 다음 특별관계자를 가나다순으로 나열한다.
    results.sort(key=lambda r: (r['reporter_name'], r['holder_name'] != r['reporter_name'], r['holder_name']))
    meta = {"lookback_years": LARGE_HOLDING_LOOKBACK_YEARS}
    _large_holding_cache.update(ts=now, data=results, meta=meta)
    return results

# ─────────────────────────────────────────────────────────────
# 3-3-5. 공정위 공시(계열회사간 거래) 모니터링 — DART의 pblntf_ty="J"(공정위공시)로
# 조회되는 여러 보고서 유형 중, 사용자가 지정한 3종(특수관계인에대한출자/채권매도,
# 동일인등출자계열회사와의상품ㆍ용역거래)만 다룬다(대규모기업집단현황공시ㆍ지급
# 수단별지급기간별지급금액및분쟁조정기구에관한사항은 제외). 근거는 독점규제 및
# 공정거래에 관한 법률 제26조(대규모내부거래의 이사회 의결 및 공시), 같은 법
# 시행령 제33조, 공정위 고시 — 사전검증 계산기(check_ftc_disclosure)도 이 근거를
# 그대로 따른다.
# ─────────────────────────────────────────────────────────────
FTC_LOOKBACK_YEARS = 10
FTC_CACHE_TTL = 6 * 3600
FTC_REPORT_TYPES = {
    'invest': '특수관계인에대한출자',
    'bond_sale': '특수관계인에대한채권매도',
    'goods_services': '동일인등출자계열회사와의상품ㆍ용역거래',
}
FTC_TYPE_LABELS = {
    'invest': '특수관계인 출자',
    'bond_sale': '특수관계인 채권매도',
    'goods_services': '상품ㆍ용역거래(동일인등출자계열회사)',
}

def _ftc_value_for(soup, *labels) -> str:
    """공정위 공시 문서는 단판공시와 마찬가지로 ACODE 없이 순수 라벨-값 <TD> 쌍으로만
    구성된 서식이다("1. 거래상대방" <TD> 바로 다음 <TD>가 값). 번호 접두어("1. ")나
    셀 안 공백 유무가 서식마다 달라 공백을 모두 제거하고 부분일치로 비교한다."""
    for td in soup.find_all('td'):
        norm = re.sub(r'\s+', '', td.get_text(strip=True))
        if any(re.sub(r'\s+', '', lbl) in norm for lbl in labels):
            nxt = td.find_next_sibling('td')
            if nxt:
                return nxt.get_text(strip=True)
    return ''

def _ftc_normalize_counterparty(name: str) -> str:
    """이 3종 공정위 공시의 거래상대방은 전부 "계열회사"(법인)라, "(주)"가 붙는 게
    정상이다. 그런데 공시마다 표기가 "(주)X"/"X(주)"로 뒤섞이는 것에 더해(대량보유
    상황보고서에서 겪은 문제와 동일), 아예 "(주)" 자체가 빠진 표기도 있다(2020년
    필기 사례: "유진기업(주)"가 어느 공시에는 "유진기업"으로만 적혀 있었음). 법인임이
    이미 확정된 필드이므로, 정규화 후에도 "(주)"가 없으면 그냥 붙인다."""
    name = _lh_normalize_name(name.strip())
    if name and not name.endswith('(주)'):
        name = name + '(주)'
    return name

def _ftc_parse_invest(soup) -> dict:
    """특수관계인에 대한 출자."""
    return {
        'counterparty': _ftc_value_for(soup, '거래상대방'),
        'relation': _ftc_value_for(soup, '회사와의관계'),
        'board_date': _ftc_value_for(soup, '이사회의결일'),
        'amount': _equity_parse_num(_ftc_value_for(soup, '출자금액')),
        'purpose': _ftc_value_for(soup, '출자목적'),
    }

def _ftc_parse_bond_sale(soup) -> dict:
    """특수관계인에 대한 채권매도."""
    return {
        'counterparty': _ftc_value_for(soup, '매도상대방'),
        'relation': _ftc_value_for(soup, '회사와의관계'),
        'board_date': _ftc_value_for(soup, '이사회의결일'),
        'amount': _equity_parse_num(_ftc_value_for(soup, '거래금액')),
        'purpose': _ftc_value_for(soup, '거래목적'),
    }

def _ftc_parse_goods_services(soup) -> dict:
    """동일인 등 출자 계열회사와의 상품ㆍ용역거래(변경). 이 서식은 두 가지 하위
    레이아웃이 섞여 있다:
    - "최초"(연 1회, 4개 분기 누적) 서식: "2. 거래상대방(...)" 라벨과 회사명이
      한 행에 나란히 있고, 분기별 매출액대비(%) 값은 "1.59%"처럼 % 기호가 붙어
      있다 — 라벨 바로 다음 <TD>, 그리고 텍스트 구간 내 "N.NN%" 정규식으로 처리.
    - "변경"(분기별 갱신) 서식: "거래상대방(...)" 등은 헤더 행에만 있고 실제 값
      (회사명ㆍ매출액대비 등)은 그 다음 데이터 행의 같은 열 위치에 있으며, 비율
      값에는 % 기호가 없다(예: "0.59") — 이 경우 헤더 행의 각 라벨이 몇 번째
      열인지 찾아, 다음 행에서 같은 열 위치의 값을 가져온다.
    두 레이아웃 모두 지원하기 위해, "거래상대방"이 포함된 라벨 셀을 찾은 뒤 같은
    행의 바로 다음 셀을 먼저 시도하고, 그 값이 "매출액(B)" 같은 다른 헤더 텍스트로
    보이면(=값이 아니라 헤더 행이었다는 뜻) 다음 행의 같은 열 위치로 대체한다."""
    board_date = _ftc_value_for(soup, '이사회의결일')
    prior_revenue = _equity_parse_num(_ftc_value_for(soup, '직전사업연도매출액'))
    text = soup.get_text(' ', strip=True)
    section_m = re.search(r'거래금액(.*?)5\.\s*상품', text, re.S)
    section = section_m.group(1) if section_m else ''
    ratios = [float(x) for x in re.findall(r'([\d.]+)\s*%', section)]

    counterparty = ''
    for td in soup.find_all('td'):
        norm = re.sub(r'\s+', '', td.get_text(strip=True))
        if '거래상대방' not in norm:
            continue
        row = td.find_parent('tr')
        cells = row.find_all('td')
        idx = cells.index(td)
        same_row_value = cells[idx + 1].get_text(strip=True) if idx + 1 < len(cells) else ''
        if same_row_value and '매출액' not in same_row_value and '매입액' not in same_row_value:
            counterparty = same_row_value  # "최초" 서식: 라벨-값이 한 행에 나란히
        else:
            # "변경" 서식: 헤더 행 다음 데이터 행의 같은 열 위치에서 회사명ㆍ비율을 가져옴
            ratio_idx = next((i for i, c in enumerate(cells)
                               if '매출액대비' in re.sub(r'\s+', '', c.get_text(strip=True))), None)
            data_row = row.find_next_sibling('tr')
            if data_row:
                data_cells = data_row.find_all('td')
                if idx < len(data_cells):
                    counterparty = data_cells[idx].get_text(strip=True)
                if not ratios and ratio_idx is not None and ratio_idx < len(data_cells):
                    m = re.match(r'-?[\d.]+', data_cells[ratio_idx].get_text(strip=True))
                    if m:
                        ratios.append(float(m.group(0)))
        break  # 문서당 "거래상대방" 라벨은 하나뿐 — 첫 매치만 처리

    return {
        'counterparty': counterparty,
        'relation': '동일인등출자계열회사',
        'board_date': board_date,
        'prior_revenue': prior_revenue,
        'max_quarterly_ratio': max(ratios) if ratios else None,
    }

_FTC_PARSERS = {
    'invest': _ftc_parse_invest,
    'bond_sale': _ftc_parse_bond_sale,
    'goods_services': _ftc_parse_goods_services,
}

_ftc_cache = {'ts': 0.0, 'data': None, 'meta': None}

def fetch_ftc_monitoring(force: bool = False) -> list:
    """최근 10년간 공정위 공시(pblntf_ty=J) 중 계열회사간 거래 관련 3종(특수관계인
    출자/채권매도, 동일인등출자계열회사와의 상품ㆍ용역거래)을 스캔해 접수일 최신순
    목록으로 반환한다. 대규모기업집단현황공시ㆍ지급수단별지급기간별지급금액및
    분쟁조정기구에관한사항은 범위에서 제외(사용자 요청)."""
    now = datetime.now().timestamp()
    if not force and _ftc_cache['data'] is not None and now - _ftc_cache['ts'] < FTC_CACHE_TTL:
        return _ftc_cache['data']

    corp_code = DART_CORP_CODES.get(DANPAN_TARGET_STOCK_CODE)
    if not corp_code or not DART_API_KEY:
        return []

    end_de = datetime.now().strftime('%Y%m%d')
    bgn_de = (datetime.now() - timedelta(days=365 * FTC_LOOKBACK_YEARS)).strftime('%Y%m%d')

    all_items = []
    page = 1
    while True:
        try:
            r = requests.get("https://opendart.fss.or.kr/api/list.json", params={
                "crtfc_key": DART_API_KEY, "corp_code": corp_code,
                "bgn_de": bgn_de, "end_de": end_de, "pblntf_ty": "J",
                "page_no": page, "page_count": 100,
            }, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[DEBUG] 공정위 공시 목록 조회 중 예외(page={page}): {e}")
            break
        if data.get('status') != '000':
            break
        all_items.extend(data.get('list', []))
        if page >= int(data.get('total_page', 1) or 1):
            break
        page += 1

    results = []
    for item in all_items:
        report_nm = item.get('report_nm', '')
        if report_nm.startswith('[기재정정]'):
            continue  # 정정본은 기존 신고서의 오기재만 바로잡는 것이라 제외
        kind = next((k for k, kw in FTC_REPORT_TYPES.items() if kw in report_nm), None)
        if kind is None:
            continue
        rcept_no = item['rcept_no']
        rcept_dt = item.get('rcept_dt', '')
        text = fetch_dart_document_text(rcept_no)
        if not text:
            continue
        soup = BeautifulSoup(text, 'html.parser')
        parsed = _FTC_PARSERS[kind](soup)

        amount_won = None
        if kind == 'goods_services':
            ratio = parsed.get('max_quarterly_ratio')
            prior_revenue = parsed.get('prior_revenue')
            amount_label = f"매출액대비 최대 {ratio:.2f}%" if ratio is not None else ''
            if ratio is not None and prior_revenue is not None:
                amount_won = round(prior_revenue * ratio / 100) * 1_000_000  # 백만원 → 원
        else:
            amt = parsed.get('amount')
            amount_label = f"{amt:,}백만원" if amt is not None else ''
            if amt is not None:
                amount_won = amt * 1_000_000

        results.append({
            "type_label": FTC_TYPE_LABELS[kind],
            "kind": kind,
            "counterparty": _ftc_normalize_counterparty(parsed.get('counterparty') or ''),
            "relation": parsed.get('relation') or '',
            "disclosure_date": _dots(f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}") if len(rcept_dt) == 8 else rcept_dt,
            "board_date": parsed.get('board_date') or '',  # 원문에 이미 "YYYY.MM.DD"로 기재됨
            "amount_label": amount_label,
            "amount_won": amount_won,
            "rcept_no": rcept_no,
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })

    results.sort(key=lambda r: r['disclosure_date'], reverse=True)  # 최신순

    # 상품ㆍ용역거래는 "동일인 및 동일인 친족이 20% 이상 출자한 계열회사(또는 그
    # 50% 초과 자회사)"만 대상이라 사용자가 특정 계열사가 여기 해당하는지 판단하기
    # 어렵다 — 최근 10년간 이 유형으로 실제 신고된 거래상대방 목록을 참고자료로
    # 함께 내려준다(완전한 목록이라는 보장은 없지만, 이미 이 규정으로 신고된
    # 이력이 있다는 것 자체가 강한 참고 근거가 된다).
    known_counterparties = sorted({
        r['counterparty'] for r in results
        if r['type_label'] == FTC_TYPE_LABELS['goods_services'] and r['counterparty']
    })

    _ftc_apply_accuracy_check(results)

    meta = {
        "lookback_years": FTC_LOOKBACK_YEARS,
        "known_goods_services_counterparties": known_counterparties,
    }
    _ftc_cache.update(ts=now, data=results, meta=meta)
    return results

def _normalize_dot_date(raw: str):
    """"2025.04.25"뿐 아니라 "2025. 4. 25."처럼 공백ㆍ트레일링 점이 섞인 원문
    표기도 파싱한다("-"처럼 날짜가 아예 없는 경우는 None)."""
    if not raw:
        return None
    cleaned = raw.replace(' ', '').strip('.')
    parts = cleaned.split('.')
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None

def _business_days_between(start_dot: str, end_dot: str):
    """두 날짜 사이의 영업일 수(토ㆍ일만 제외, 공휴일은 반영 못함 — 근사치)를
    센다. 시작일 당일은 세지 않고(이사회 의결 당일은 포함하지 않음) 종료일까지
    며칠째인지를 반환한다. 파싱 실패ㆍ날짜 역전 시 None(=확인불가)."""
    d1, d2 = _normalize_dot_date(start_dot), _normalize_dot_date(end_dot)
    if d1 is None or d2 is None or d2 < d1:
        return None
    days = 0
    cur = d1
    while cur < d2:
        cur += timedelta(days=1)
        if cur.weekday() < 5:  # 월~금
            days += 1
    return days

FTC_FILING_DEADLINE_BUSINESS_DAYS = 3  # 동양(주)은 상장법인 — 이사회 의결 후 3영업일 이내 공시

def _ftc_apply_accuracy_check(results: list) -> None:
    """이미 제출된 공정위 공시 건들을 대상으로 "정확성 점검"을 덧붙인다(자동
    판정이 아니라 확인 필요 후보를 추려주는 용도):
    1) 공시기한 준수 — 이사회 의결일로부터 실제 공시일까지 영업일수를 계산해
       3영업일(동양(주)은 상장법인) 초과 여부를 표시.
    2) 공시대상 재확인 — 원문에서 뽑은 거래금액(amount_won)과 동양(주)의 "현재"
       자본총계·자본금 중 큰 금액으로 check_ftc_disclosure()를 다시 돌려본다.
       이미 신고된 건이니 거의 항상 "대상"으로 나와야 정상 — False가 나오면
       자본금이 신고 당시와 달라졌거나 원문 파싱이 어긋났을 수 있어 확인이
       필요하다는 신호로 취급한다(과거 시점 자본금이 아니라 현재 값을 쓰는
       근사치라는 한계를 화면에도 명시해야 함)."""
    dongyang = next((r for r in fetch_all_group_capital_info() if r['name'] == '동양(주)'), None)
    capital_base = dongyang.get('capital_base') if dongyang else None

    for r in results:
        business_days = _business_days_between(r.get('board_date') or '', r.get('disclosure_date') or '')
        r['filing_business_days'] = business_days
        # 'on_time'/'late'/'unknown' — bool 대신 3단계로 둬서 "확인불가"가
        # "지연"으로 잘못 읽히지 않게 한다(예: 1년 일괄의결 특례라 이사회
        # 의결일이 "-"로 비어 있는 상품ㆍ용역거래 분기 공시 등).
        r['filing_timeliness'] = (
            'unknown' if business_days is None
            else 'on_time' if business_days <= FTC_FILING_DEADLINE_BUSINESS_DAYS
            else 'late'
        )

        reverify = None
        if r.get('amount_won') is not None and capital_base:
            transaction_type = 'goods_services' if r.get('kind') == 'goods_services' else 'fund_securities_asset'
            reverify = check_ftc_disclosure(transaction_type, r['amount_won'], capital_base, is_goods_services_target=True)
        r['reverify_is_required'] = reverify['is_disclosure_required'] if reverify else None
        r['reverify_note'] = (
            "원문 금액ㆍ현재 자본 기준으로도 공시대상 요건을 충족합니다(참고: 자본금은 신고 당시가 아닌 현재 값)."
            if reverify and reverify['is_disclosure_required']
            else "원문 금액ㆍ현재 자본 기준으로는 공시대상 요건에 못 미칩니다 — 신고 당시 자본금이 지금과 달랐거나 확인이 필요할 수 있습니다."
            if reverify
            else "거래금액 또는 자본금 데이터가 부족해 재확인할 수 없습니다."
        )

# ─────────────────────────────────────────────────────────────
# 3-3-6. 비상장 계열사 자본금ㆍ자본총계 — 공정위 대규모내부거래 사전검증용.
# 비상장회사는 사업보고서를 제출하지 않아 fnlttSinglAcntAll로 조회가 안 되지만,
# 공시대상기업집단 소속회사는 상장 여부와 무관하게 매년 "기업집단현황공시
# (연1회-개별회사용)"를 제출하고, 그 안의 "(2) 회사 재무현황"표에 개별
# 재무상태표 기준 자본금ㆍ자본총계가 실제로 나온다 — 이걸로 대체 조회한다.
# ─────────────────────────────────────────────────────────────
FTC_SUBSIDIARY_CORP_CODES = {
    "금왕에프원(주)": {"corp_code": "01718540", "biz_reg_no": "662-88-02269"},
    "유진한일합섬(주)": {"corp_code": "01281860", "biz_reg_no": "734-81-00946"},
    "유진홈센터(주)": {"corp_code": "00856931", "biz_reg_no": "483-81-00994"},
    "디씨아이티와이부천피에프브이(주)": {"corp_code": "01971228", "biz_reg_no": "406-86-03271"},
    "디씨아이티와이인천피에프브이(주)": {"corp_code": "01971200", "biz_reg_no": "542-81-04061"},
}
# ─────────────────────────────────────────────────────────────
# 3-3-7. 상품ㆍ용역거래 상대방 판단용 — "동일인 및 동일인 친족 20% 이상 출자
# 계열회사(A)ㆍ그 50% 초과 자회사(B, 상법 제342조의2에 따라 사슬로 이어지는
# 손자회사ㆍ증손회사까지 포함)" 실제 목록. 자금ㆍ유가증권ㆍ자산 거래는
# 특수관계인이면 바로 대상이지만, 상품ㆍ용역거래는 이 좁은 범위의 회사만
# 대상이라 "어디가 여기 해당하는지" 사용자가 판단하기 어렵다는 게 계속
# 지적된 문제였다.
#
# 처음엔 그룹 대표회사(유진기업㈜)가 매년 내는 "기업집단현황공시(연1회-대표
# 회사)"의 "(16) 특수관계인 지분율이 높은 계열회사의 내부거래 현황"에 나온
# 회사명만 모았는데(18개사), 이 표는 "실제 거래 실적이 있는 회사"만 신고하는
# 표라 이 정의에 해당하지만 최근 3개년간 거래가 전혀 없었던 회사는 빠진다는
# 걸 사용자가 실제 27개사 목록과 대조해 발견했다. 대신 같은 공시의
# "(1) 소유지분현황" 표(회사마다 동일인ㆍ친족ㆍ계열회사 등 주주 구성을 그대로
# 신고하는 표)에서 직접 계산하면 "거래 실적 유무와 무관하게" 정의 그대로
# 판단할 수 있다:
#   1) A = 동일인 지분율 + 친족 합계 지분율이 20% 이상인 회사
#   2) B = A(또는 이미 B로 확정된 회사)가 50% 초과 보유한 계열회사 — 사슬로
#      계속 확장(상법 제342조의2 제3항, 자회사의 자회사도 모회사의 자회사로
#      본다는 조항)
# 이 계산으로 실제 사용자가 제시한 27개사와 정확히 일치함을 검증했다(사모
# 투자"합자회사"는 지분(주식)이 아니라 조합 지분이라 상법 342조의2의 "자회사"
# 정의(발행주식 기준) 자체가 적용되지 않아 제외 — 실제로 유진더블유사모투자
# 합자회사가 유진기업㈜ 지분 56.98%를 보유해 계산상 걸렸으나 사용자 목록에는
# 없어 이 예외를 확인함).
# ─────────────────────────────────────────────────────────────
FTC_GROUP_REP_CORP_CODE = "00184667"  # 유진기업(주) — 유진 기업집단 대표회사
GOODS_SERVICES_TARGETS_CACHE_TTL = 24 * 3600
FUND_ENTITY_MARKERS = ('합자회사', '투자조합', '사모투자전문회사')  # 주식이 아닌 지분(조합원권)이라 상법 342조의2 자회사 정의 대상이 아님

def _parse_pct_float(text: str) -> float:
    text = (text or '').strip()
    if not text or text == '-':
        return 0.0
    try:
        return float(text.replace(',', ''))
    except ValueError:
        return 0.0

def _expand_rowspan_grid(trs) -> list:
    """DART 소유지분현황 표처럼 ROWSPAN이 수백 행까지 이어지는 표를, bs4가
    자동으로 채워주지 않는 생략된 셀까지 채워서 행렬(list of dict) 형태로
    편다 — 표를 눈으로 보는 것과 동일한 완전한 행을 얻기 위함."""
    pending = {}  # col_idx -> [남은 행 수, 텍스트]
    grid = []
    for tr in trs:
        cells = tr.find_all(['td', 'th'])
        row_vals = {}
        col = 0
        ci = 0
        while True:
            if col in pending and pending[col][0] > 0:
                row_vals[col] = pending[col][1]
                pending[col][0] -= 1
                if pending[col][0] == 0:
                    del pending[col]
                col += 1
                continue
            if ci >= len(cells):
                break
            cell = cells[ci]
            text = cell.get_text(strip=True)
            rowspan = int(cell.get('rowspan', 1) or 1)
            colspan = int(cell.get('colspan', 1) or 1)
            for k in range(colspan):
                row_vals[col + k] = text
                if rowspan > 1:
                    pending[col + k] = [rowspan - 1, text]
            col += colspan
            ci += 1
        grid.append(row_vals)
    return grid

def _group_status_parse_ownership(html_text: str) -> dict:
    """"기업집단현황공시"의 "(1) 소유지분현황" 표에서 회사별 동일인 지분율ㆍ
    친족 합계 지분율ㆍ계열회사 보유자별 지분율을 뽑는다.
    반환: {회사명: {"owner_pct": float, "family_pct": float, "affiliates": [(보유계열사명, 지분율), ...]}}"""
    soup = BeautifulSoup(html_text, 'html.parser')
    marker = soup.find(string=lambda s: s and '소유지분현황' in s)
    if not marker:
        return {}
    table = None
    for t in marker.find_all_next('table')[:4]:
        if len(t.find_all('tr')) > 5:
            table = t
            break
    if table is None:
        return {}

    grid = _expand_rowspan_grid(table.find_all('tr')[2:])  # 헤더 2줄 제외
    if not grid:
        return {}
    ncols = max(max(r.keys()) for r in grid) + 1
    rows = [[r.get(i, '') for i in range(ncols)] for r in grid]

    companies = {}
    for row in rows:
        if len(row) < 6 or not row[1]:
            continue
        name = row[1]
        c = companies.setdefault(name, {"owner_pct": 0.0, "family_pct": 0.0, "affiliates": []})
        if row[2] == '동일인측' and row[3] == '동일인':
            c["owner_pct"] = _parse_pct_float(row[-1])
        if row[3] == '친족' and '친족 합계' in row[4]:
            c["family_pct"] = _parse_pct_float(row[-1])
        if row[3] == '계열회사(국내+해외)':
            owner, pct = row[5], _parse_pct_float(row[-1])
            if owner and owner != '-':
                c["affiliates"].append((owner, pct))
    return companies

def _compute_goods_services_targets(companies: dict) -> list:
    """소유지분 데이터로 "동일인 등 출자 계열회사(A)ㆍ그 50% 초과 자회사(B)"를
    계산한다 — 사슬로 이어지는 손자회사까지 반복 확장(고정점에 도달할 때까지)."""
    norm = lambda n: _lh_normalize_name(n.replace('㈜', '(주)'))
    normalized = {norm(name): data for name, data in companies.items()}

    target = {name for name, c in normalized.items() if c["owner_pct"] + c["family_pct"] >= 20.0}
    changed = True
    while changed:
        changed = False
        for name, c in normalized.items():
            if name in target:
                continue
            for owner, pct in c["affiliates"]:
                if norm(owner) in target and pct > 50.0:
                    target.add(name)
                    changed = True
                    break

    # 합자회사 등 지분(조합원권) 기반 법인은 상법 342조의2의 "발행주식" 기준
    # 자회사 정의 대상이 아니므로 결과에서 제외한다.
    target = {name for name in target if not any(marker in name for marker in FUND_ENTITY_MARKERS)}
    return sorted(target)

_goods_services_targets_cache = {'ts': 0.0, 'data': None}
_group_rep_doc_cache = {'ts': 0.0, 'text': None, 'rcept_no': None, 'rcept_dt': None}

def _fetch_group_rep_document(force: bool = False) -> dict:
    """유진 기업집단 대표회사(유진기업㈜)의 최신 "기업집단현황공시(연1회-대표
    회사)" 원문을 캐시해서 재사용한다 — "(1) 소유지분현황"(20% 계열사 계산)과
    "(2) 회사 재무현황"(전체 계열사 자본금ㆍ자본총계)이 같은 문서 안에 있어서,
    두 계산이 같은 다운로드를 공유하면 DART 호출을 절반으로 줄일 수 있다."""
    now = datetime.now().timestamp()
    if not force and _group_rep_doc_cache['text'] is not None and now - _group_rep_doc_cache['ts'] < GOODS_SERVICES_TARGETS_CACHE_TTL:
        return _group_rep_doc_cache

    if not DART_API_KEY:
        return _group_rep_doc_cache

    end_de = datetime.now().strftime('%Y%m%d')
    bgn_de = (datetime.now() - timedelta(days=400)).strftime('%Y%m%d')
    items = [
        d for d in fetch_dart_disclosures(FTC_GROUP_REP_CORP_CODE, bgn_de, end_de)
        if '연1회' in d.get('report_nm', '') and '대표회사' in d.get('report_nm', '')
    ]
    if items:
        latest = max(items, key=lambda d: d['rcept_dt'])
        text = fetch_dart_document_text(latest['rcept_no'])
        if text:
            _group_rep_doc_cache.update(ts=now, text=text, rcept_no=latest['rcept_no'], rcept_dt=latest['rcept_dt'])
    return _group_rep_doc_cache

def fetch_goods_services_target_companies(force: bool = False) -> dict:
    """유진 기업집단 대표회사(유진기업㈜)의 최신 "기업집단현황공시(연1회-대표
    회사)"의 소유지분현황 데이터로 상품ㆍ용역거래 특례 대상 회사 목록을
    계산한다. 매년 갱신되는 자료라 24시간 캐시."""
    now = datetime.now().timestamp()
    if not force and _goods_services_targets_cache['data'] is not None and now - _goods_services_targets_cache['ts'] < GOODS_SERVICES_TARGETS_CACHE_TTL:
        return _goods_services_targets_cache['data']

    result = {"companies": [], "rcept_no": None, "dart_url": None, "disclosure_date": None}
    doc = _fetch_group_rep_document(force=force)
    if doc.get('text'):
        ownership = _group_status_parse_ownership(doc['text'])
        companies = _compute_goods_services_targets(ownership) if ownership else []
        rcept_dt = doc['rcept_dt']
        result = {
            "companies": companies,
            "rcept_no": doc['rcept_no'],
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={doc['rcept_no']}",
            "disclosure_date": _dots(f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}") if len(rcept_dt) == 8 else rcept_dt,
        }

    _goods_services_targets_cache.update(ts=now, data=result)
    return result

def _group_status_parse_all_capital(html_text: str) -> dict:
    """"기업집단현황공시(연1회-대표회사)"의 "(2) 회사 재무현황" 표에서 유진
    기업집단 소속 회사 전체(약 70개사)의 자산총계ㆍ자본금ㆍ자본총계(백만원
    단위)를 한 번에 뽑는다 — 개별회사용 공시를 회사마다 따로 조회하지 않아도
    되므로, 지금 화면에서 다루는 5개 비상장 자회사뿐 아니라 동양(주)ㆍ
    유진기업(주) 등 이름만 입력해도 자동으로 매칭될 수 있게 해준다.
    반환: {정규화된 회사명: {"capital_mm": .., "capital_total_mm": .., "total_assets_mm": ..}}"""
    soup = BeautifulSoup(html_text, 'html.parser')
    marker = soup.find(string=lambda s: s and '개별 재무상태표 기준 재무현황' in s)
    if not marker:
        return {}
    table = None
    for t in marker.find_all_next('table')[:4]:
        if len(t.find_all('tr')) > 5:
            table = t
            break
    if table is None:
        return {}

    rows_trs = table.find_all('tr')
    header2 = [c.get_text(strip=True).replace(' ', '') for c in rows_trs[1].find_all(['td', 'th'])]
    if '자본금' not in header2 or '자본총계' not in header2:
        return {}
    cap_idx = header2.index('자본금') + 2
    capsum_idx = header2.index('자본총계') + 2
    asset_idx = header2.index('자산총계(a+b)') + 2 if '자산총계(a+b)' in header2 else None

    grid = _expand_rowspan_grid(rows_trs[2:])
    if not grid:
        return {}
    ncols = max(max(r.keys()) for r in grid) + 1
    rows = [[r.get(i, '') for i in range(ncols)] for r in grid]

    result = {}
    for row in rows:
        if len(row) <= max(cap_idx, capsum_idx) or len(row) <= 1:
            continue
        name = row[1]
        if not name or name in ('소계', '합계'):
            continue
        capital_mm = _equity_parse_num(row[cap_idx])
        capital_total_mm = _equity_parse_num(row[capsum_idx])
        if capital_mm is None and capital_total_mm is None:
            continue
        total_assets_mm = _equity_parse_num(row[asset_idx]) if asset_idx is not None and len(row) > asset_idx else None
        norm_name = _lh_normalize_name(name.replace('㈜', '(주)'))
        result[norm_name] = {"capital_mm": capital_mm, "capital_total_mm": capital_total_mm, "total_assets_mm": total_assets_mm}
    return result

_all_capital_cache = {'ts': 0.0, 'data': None}

def fetch_all_group_capital_info(force: bool = False) -> list:
    """유진 기업집단 대표회사 공시 하나로 그룹 소속 회사 전체(약 70개사)의
    자본금ㆍ자본총계ㆍ자산총계를 반환한다. 프런트엔드는 이 중 비상장 자회사
    5개사만 드롭다운에 노출하고(is_known_subsidiary), 나머지는 "직접입력"
    칸에 이름을 치면 이 전체 목록과 자동 대조해 자본금을 채운다."""
    now = datetime.now().timestamp()
    if not force and _all_capital_cache['data'] is not None and now - _all_capital_cache['ts'] < GOODS_SERVICES_TARGETS_CACHE_TTL:
        return _all_capital_cache['data']

    results = []
    doc = _fetch_group_rep_document(force=force)
    if doc.get('text'):
        parsed = _group_status_parse_all_capital(doc['text'])
        rcept_dt = doc['rcept_dt']
        disclosure_date = _dots(f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}") if rcept_dt and len(rcept_dt) == 8 else rcept_dt
        dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={doc['rcept_no']}" if doc.get('rcept_no') else None
        known_subsidiary_names = {_lh_normalize_name(n.replace('㈜', '(주)')): info for n, info in FTC_SUBSIDIARY_CORP_CODES.items()}
        for name, v in parsed.items():
            capital = v['capital_mm'] * 1_000_000 if v['capital_mm'] is not None else None
            capital_total = v['capital_total_mm'] * 1_000_000 if v['capital_total_mm'] is not None else None
            total_assets = v['total_assets_mm'] * 1_000_000 if v.get('total_assets_mm') is not None else None
            values = [x for x in (capital, capital_total) if x is not None]
            capital_base = max(values) if values else None
            sub_info = known_subsidiary_names.get(name)
            results.append({
                "name": name,
                "biz_reg_no": sub_info['biz_reg_no'] if sub_info else None,
                "is_known_subsidiary": sub_info is not None,
                "total_assets": total_assets,
                "capital": capital,
                "capital_total": capital_total,
                "capital_base": capital_base,
                "is_large_unlisted_co": total_assets is not None and total_assets >= 100_000_000_000,
                "basis_note": "직전 사업연도말 개별 재무상태표 기준",
                "disclosure_date": disclosure_date,
                "rcept_no": doc.get('rcept_no'),
                "dart_url": dart_url,
            })

    results.sort(key=lambda r: r['name'])
    _all_capital_cache.update(ts=now, data=results)
    return results

def check_ftc_disclosure(transaction_type: str, amount: int, capital_base: int, is_goods_services_target: bool = True):
    """대규모내부거래 이사회 의결ㆍ공시 대상 여부를 판단한다(공정거래법 제26조,
    시행령 제33조, 공정위 고시 기준).

    - 공통 거래금액 기준: 거래금액이 100억원 이상이거나, 회사의 자본총계ㆍ자본금 중
      큰 금액(capital_base)의 5% 이상(단, 그 5% 값이 5억원 미만이면 5억원을 기준으로
      적용 — 즉 최소 5억원은 넘어야 공시대상).
    - transaction_type: 'fund_securities_asset'(자금ㆍ유가증권ㆍ자산 거래) 또는
      'goods_services'(상품ㆍ용역 거래).
    - goods_services 거래는 위 금액기준을 충족하더라도, 거래상대방이 "동일인 및
      동일인 친족이 발행주식총수의 20% 이상을 소유한 계열회사(또는 그 계열회사의
      상법상 50% 초과 자회사)"인 경우에만 대상이다 — is_goods_services_target
      (호출부에서 사용자가 체크)이 False면 상대방 요건 자체를 충족하지 못해
      금액과 무관하게 대상이 아니다.
    """
    if amount is None or capital_base is None or capital_base <= 0:
        return None
    threshold = max(capital_base * 0.05, 500_000_000)
    amount_ge_100eok = amount >= 10_000_000_000
    amount_ge_capital_pct = amount >= threshold
    amount_triggered = amount_ge_100eok or amount_ge_capital_pct
    is_goods = transaction_type == 'goods_services'

    base = {
        "transaction_type": transaction_type,
        "amount_ge_100eok": amount_ge_100eok,
        "amount_ge_capital_pct": amount_ge_capital_pct,
        "amount_triggered": amount_triggered,
        "threshold_amount": int(threshold),
    }

    # 판단근거 문장 — 어떤 조건이 실제로 충족을 갈랐는지 그대로 짚어준다
    # (100억 기준인지, 100억은 안 되지만 5% 기준으로 걸렸는지, 상품ㆍ용역거래는
    # 거래상대방 요건이 먼저인지 등).
    if is_goods and not is_goods_services_target:
        reason = "거래상대방이 상품ㆍ용역거래 특례 대상 계열회사(20% 계열사)에 해당하지 않아, 금액과 무관하게 공시대상이 아닙니다."
        return {**base, "is_disclosure_required": False, "reason": reason}

    if amount_ge_100eok and amount_ge_capital_pct:
        amount_reason = "거래금액이 100억원 이상이고 자본총계ㆍ자본금 중 큰 금액의 5%(최소 5억원) 기준도 충족해 공시대상입니다."
    elif amount_ge_100eok:
        amount_reason = "거래금액이 100억원 이상이므로 공시대상입니다."
    elif amount_ge_capital_pct:
        amount_reason = "거래금액은 100억원 미만이지만, 자본총계ㆍ자본금 중 큰 금액의 5%(최소 5억원) 기준을 충족해 공시대상입니다."
    else:
        amount_reason = "거래금액이 100억원 미만이고 자본총계ㆍ자본금 중 큰 금액의 5%(최소 5억원) 기준도 충족하지 않아 공시대상이 아닙니다."

    reason = f"거래상대방이 상품ㆍ용역거래 특례 대상 계열회사(20% 계열사)에 해당하며, {amount_reason}" if is_goods else amount_reason

    return {**base, "is_disclosure_required": bool(amount_triggered), "reason": reason}

# 종목 공시 게시판에는 "단기과열종목 지정"처럼 반복적으로 계속 연장되는 조치와
# "매매거래정지및정지해제"처럼 당일 안에 풀리는 일회성 조치가 섞여 있어서,
# 여러 날 이어지는 실제 거래정지의 '진짜' 원인을 공시 제목만 보고 자동으로
# 정확히 골라내기 어렵다 (예: 2026.07 동양 거래정지는 실제로는 액면(주식)병합이
# 원인이었는데, 자동 매칭은 시점상 가장 최근인 "단기과열종목 지정 연장" 공시를
# 잘못 골랐었음). DART_API_KEY가 설정돼 있으면 fetch_dart_halt_info가 이 사유를
# 훨씬 정확하게(정지기간까지) 알려주므로 우선 사용되고, 이 딕셔너리는 DART 조회가
# 안 될 때(키 미설정 등)의 최후 폴백으로만 쓰인다. 종목코드를 키로 사용.
MANUAL_HALT_REASONS = {
    # "종목코드": "확인된 사유",
}

def generate_stock_commentary(code: str, display_name: str) -> str:
    """
    최근 10영업일 수급(개인/기관/외국인)·주가 데이터를 분석해 보고서 톤 코멘트를 생성.
    순서: ① 가장 최근 실제 거래일의 시가→(장중 급변동)→종가 흐름 + 그날 수급 우위(원인) +
    관련 뉴스 — 변동폭과 무관하게 항상 서술 ② 연속 순매수/순매도 스트릭(3일 이상)
    ③ 최근 며칠간 거래가 없으면 실시간 API로 실제 거래정지 여부를 확인. MANUAL_HALT_REASONS에
    확인된 사유가 있으면 그걸 그대로 쓰고, 없으면 공시 목록에서 추정 매칭하되 "확정"이
    아니라 "추정"으로만 표현. 거래정지가 아니면 단순 저유동성으로 표시.
    데이터에서 직접 확인되지 않는 원인은 추정해 서술하지 않고,
    수치로 확인된 사실과 실제 뉴스 헤드라인만 근거로 사용한다.
    """
    history = fetch_stock_investor(code, days=10)
    if not history:
        return f"{display_name}: 수급 데이터를 불러오지 못했습니다."
    hist_by_date = {h['date']: h for h in history}

    sentences = []

    # ① 당일(최근 거래일) 동향 — 항상 서술
    ohlc_asc = fetch_daily_ohlc(code, count=12)
    news = fetch_stock_news(code, count=10)
    if ohlc_asc:
        day_sentence = _describe_latest_trading_day(code, display_name, ohlc_asc, hist_by_date, news)
        if day_sentence:
            sentences.append(day_sentence)

    # ② 연속 순매수/순매도 스트릭
    inst_sign, inst_n = _find_streak(history, 'institution')
    if inst_n >= 3:
        sentences.append(f"기관이 {inst_n}일 연속 {'순매수' if inst_sign > 0 else '순매도'} 중")

    for_sign, for_n = _find_streak(history, 'foreign')
    if for_n >= 3:
        sentences.append(f"외국인이 {for_n}일 연속 {'순매수' if for_sign > 0 else '순매도'} 중")

    # ③ 거래정지 여부 (현재 상태이므로 맨 뒤에 배치)
    zero_n = _find_zero_volume_streak(history)
    if zero_n >= 2:
        status = fetch_trade_status(code)
        if status['halted']:
            dart_info = fetch_dart_halt_info(code)
            if dart_info and dart_info.get('start') and dart_info.get('end'):
                sentences.append(
                    f"현재 거래정지 상태. DART 공시(「{dart_info['reason']}」, {dart_info['date']}) 확인 결과 "
                    f"매매거래정지기간은 {dart_info['start']}~{dart_info['end']}"
                )
            elif dart_info:
                sentences.append(f"현재 거래정지 상태. 관련 DART 공시: 「{dart_info['reason']}」({dart_info['date']})")
            else:
                manual_reason = MANUAL_HALT_REASONS.get(code)
                if manual_reason:
                    # 조사(으로/로) 활용 문제를 피하려고 콜론 구조로 표현
                    sentences.append(f"현재 거래정지 상태. 확인된 사유: {manual_reason}")
                else:
                    notices = fetch_stock_notices(code, count=5)
                    HALT_KEYWORDS = ['정지', '단기과열', '단일가매매', '병합']
                    reason = next((n for n in notices if any(k in n['title'] for k in HALT_KEYWORDS)), None)
                    if reason:
                        # 공시 목록에 정지 관련 항목이 있어도, 여러 날 이어지는 이번 정지의
                        # '진짜' 원인인지는 자동으로 단정할 수 없어 추정으로만 표현한다.
                        sentences.append(
                            f"현재 거래정지 상태 — 관련 가능성이 있는 최근 공시로 「{reason['title']}」({reason['date']})가 "
                            f"있으나, 이번 정지와의 정확한 인과관계는 확인되지 않음"
                        )
                    else:
                        sentences.append(f"현재 거래정지 상태 (최근 {zero_n}거래일간 거래 없음, 구체적 사유 공시는 확인되지 않음)")
        else:
            sentences.append(f"현재는 최근 {zero_n}거래일간 거래대금이 사실상 '0'으로 초저유동성 상태")

    if not sentences:
        sentences.append("최근 10영업일간 수급·주가 흐름에 뚜렷한 특이사항 없음")

    return f"{display_name}: " + '. '.join(sentences) + '.'

# ─────────────────────────────────────────────────────────────
# 4. 환율
# ─────────────────────────────────────────────────────────────
def _exchange_entry(entry: dict) -> dict:
    """API 응답 한 행 -> {usd_to_krw, change, direction} 포맷 변환"""
    rate = float(str(entry['closePrice']).replace(',', ''))
    diff = float(str(entry.get('fluctuations', '0')).replace(',', ''))
    pct  = float(str(entry.get('fluctuationsRatio', '0')).replace(',', ''))
    sign = '+' if diff > 0 else ''
    direction = 'up' if diff > 0 else ('down' if diff < 0 else '')
    arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '-')
    change_str = f"{sign}{fmt_num(diff)} ({sign}{fmt_num(pct)}% {arrow})" if diff or pct else ''
    return {"usd_to_krw": fmt_num(rate), "change": change_str, "direction": direction}

def fetch_exchange() -> dict:
    """
    네이버 marketindex 환율 API(일자별 시리즈)로 USD/KRW 조회
    - 현재기준: 오늘(가장 최근) 데이터 - 외환은 24시간 거래되므로 계속 갱신됨
    - 장마감기준: 직전 영업일의 확정 종가 (오늘자는 아직 미확정이므로 제외)
    """
    url = "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices"
    na = {"usd_to_krw": "N/A", "change": "", "direction": ""}
    try:
        r = requests.get(url, headers=HEADERS, params={"page": 1, "pageSize": 2}, timeout=8)
        datas = r.json()
        current = _exchange_entry(datas[0]) if len(datas) > 0 else na
        close   = _exchange_entry(datas[1]) if len(datas) > 1 else current
        return {"current": current, "close": close}
    except Exception as e:
        print(f"[DEBUG] 환율 조회 중 예외: {e}")
        return {"current": na, "close": na}

# ─────────────────────────────────────────────────────────────
# 디버깅용 (문제 생기면 실행해서 원본 HTML 확인)
# ─────────────────────────────────────────────────────────────
def debug_dump_main_page(ticker: str):
    main_url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    mr = requests.get(main_url, headers=HEADERS, timeout=10)
    mr.encoding = 'utf-8'
    with open(f"debug_{ticker}.html", "w", encoding="utf-8") as f:
        f.write(mr.text)
    print(f"저장 완료: debug_{ticker}.html (상태코드 {mr.status_code})")

def debug_dump_investor_page(code: str = "KOSPI"):
    url = f"https://finance.naver.com/sise/sise_index_investor.naver?code={code}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    raw = r.content.decode('utf-8', errors='replace')
    with open(f"debug_investor_{code}.html", "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"저장 완료: debug_investor_{code}.html (상태코드 {r.status_code})")

# ─────────────────────────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────────────────────────

@app.route('/data')
def data_endpoint():
    section = request.args.get('section', '')

    if section == 'indices':
        return jsonify({
            "kospi":  fetch_index('KOSPI'),
            "kosdaq": fetch_index('KOSDAQ'),
        })

    if section == 'themes':
        # 리스트(name, no) 순서 그대로 노출됨 — dict를 쓰면 Flask의 JSON_SORT_KEYS
        # 기본값(True) 때문에 키가 가나다순으로 재정렬되어 순서가 무시된다.
        THEMES = [
            ("시멘트/레미콘", 44),
            ("건설대표주", 154),
            ("증권", 151),
            ("미디어(방송/신문)", 232),
        ]
        result = [{"name": name, **fetch_theme_change(no)} for name, no in THEMES]
        return jsonify(result)

    if section == 'companies':
        COMPANIES = {
            "동양":         "001520",
            "유진기업":     "023410",
            "유진투자증권": "001200",
            "YTN":          "040300",
            "티엑스알로보틱스": "484810",
        }
        # DART 재무제표 조회가 안 될 때만 쓰는 폴백값 (DART_API_KEY 미설정 등).
        # 종목마다 액면가/우선주 구성이 달라 수동 계산은 부정확할 수 있어서
        # fetch_dart_capital()이 우선이고, 이건 최후 수단일 뿐이다.
        CAPITAL_FALLBACK = {
            "동양":         "1,199",
            "유진기업":     "387",
            "유진투자증권": "5,376",
            "YTN":          "477",
            "티엑스알로보틱스": "77",
        }
        result = []
        for name, code in COMPANIES.items():
            d = fetch_stock(code)
            d['display_name'] = name
            dart_capital = fetch_dart_capital(code)
            d['capital_billion'] = f"{dart_capital:,}" if dart_capital is not None else CAPITAL_FALLBACK.get(name, '0')
            result.append(d)
        return jsonify(result)

    if section == 'cement':
        CEMENT = {
            "한일시멘트":   "300720",
            "성신양회":     "004980",
            "삼표시멘트":   "038500",
            "아세아시멘트": "183190",
            "강동씨앤엘":   "198440",
        }
        # DART 재무제표 조회가 안 될 때만 쓰는 폴백값. 예전엔 "보통주 × 5,000원
        # 액면가"로 추정 계산했었는데, 실제 DART 공시와 대조해보니 종목별로
        # 액면가가 500원인 곳도 있어 틀린 값이 섞여있었다(한일시멘트 310→368억,
        # 성신양회 300→1,285억). fetch_dart_capital()이 실측값이라 우선한다.
        CAPITAL_FALLBACK = {
            "한일시멘트":   "310",
            "성신양회":     "300",
            "삼표시멘트":   "254",
            "아세아시멘트": "204",
            "강동씨앤엘":   "63",
        }
        result = []
        for name, code in CEMENT.items():
            d = fetch_stock(code)
            d['display_name'] = name
            dart_capital = fetch_dart_capital(code)
            d['capital_billion'] = f"{dart_capital:,}" if dart_capital is not None else CAPITAL_FALLBACK.get(name, '0')
            result.append(d)
        return jsonify(result)

    if section == 'exchange':
        return jsonify(fetch_exchange())

    if section == 'investor_detail':
        code = request.args.get('code', '')
        if not code:
            return jsonify({"error": "code parameter required"}), 400
        return jsonify(fetch_stock_investor(code))

    if section == 'commentary':
        # 인쇄(PDF) 시 표 아래 남는 여백에 넣을 주가 동향 코멘트 — 동양/유진기업 대상
        TARGETS = [("동양", "001520"), ("유진기업", "023410")]
        lines = [generate_stock_commentary(code, name) for name, code in TARGETS]
        return jsonify({"lines": lines})

    if section == 'danpan':
        force = request.args.get('refresh') == '1'
        sites = fetch_danpan_monitoring(force=force)
        return jsonify({"sites": sites, "meta": _danpan_cache.get('meta') or {}})

    if section == 'equity':
        force = request.args.get('refresh') == '1'
        records = fetch_equity_monitoring(force=force)
        return jsonify({"records": records, "meta": _equity_cache.get('meta') or {}})

    if section == 'equity_accuracy':
        force = request.args.get('refresh') == '1'
        fetch_equity_monitoring(force=force)  # 캐시를 채워야 accuracy도 함께 채워짐
        return jsonify(_equity_cache.get('accuracy') or {
            "issued_shares_total": {"current_value": None, "timeline": [], "same_day_conflicts": []},
            "officer_appointment_issues": [],
            "share_count_issues": [],
        })

    if section == 'large_holding':
        force = request.args.get('refresh') == '1'
        records = fetch_large_holding_monitoring(force=force)
        return jsonify({"records": records, "meta": _large_holding_cache.get('meta') or {}})

    if section == 'ftc':
        force = request.args.get('refresh') == '1'
        range_param = request.args.get('range', 'recent')  # 'recent'(최근 1년, 기본) | 'all'(최근 10년 전체)
        records = fetch_ftc_monitoring(force=force)
        meta = dict(_ftc_cache.get('meta') or {})
        if range_param != 'all':
            cutoff = (datetime.now() - timedelta(days=365)).strftime('%Y.%m.%d')
            filtered = [r for r in records if r.get('disclosure_date', '') >= cutoff]
            meta['range'] = 'recent'
            meta['total_count_all_years'] = len(records)
            records = filtered
        else:
            meta['range'] = 'all'
        return jsonify({"records": records, "meta": meta})

    if section == 'ftc_check':
        transaction_type = request.args.get('transaction_type', '')
        amount_raw = request.args.get('amount', '')
        capital_raw = request.args.get('capital_base', '')
        is_target_raw = request.args.get('is_goods_services_target', '1')
        if transaction_type not in ('fund_securities_asset', 'goods_services'):
            return jsonify({"error": "transaction_type은 fund_securities_asset 또는 goods_services 여야 합니다."}), 400
        try:
            amount = int(amount_raw)
            capital_base = int(capital_raw)
        except ValueError:
            return jsonify({"error": "거래금액(amount)ㆍ자본총계·자본금 중 큰 금액(capital_base)은 원 단위 숫자로 입력해주세요."}), 400
        result = check_ftc_disclosure(transaction_type, amount, capital_base, is_target_raw != '0')
        if result is None:
            return jsonify({"error": "판단할 수 없습니다 — 입력값을 확인해주세요."}), 400
        return jsonify(result)

    if section == 'subsidiary_capital':
        force = request.args.get('refresh') == '1'
        records = fetch_all_group_capital_info(force=force)
        return jsonify({"records": records})

    if section == 'goods_services_targets':
        force = request.args.get('refresh') == '1'
        return jsonify(fetch_goods_services_target_companies(force=force))

    if section == 'danpan_check':
        contract_date = request.args.get('contract_date', '')
        amount_raw = request.args.get('amount', '')
        try:
            amount = int(amount_raw)
        except ValueError:
            return jsonify({"error": "계약금액(amount)은 원 단위 숫자로 입력해주세요."}), 400
        result = check_danpan_disclosure(contract_date, amount)
        if result is None:
            return jsonify({"error": "판단할 수 없습니다 — 계약일자 형식(YYYY-MM-DD)을 확인하거나, DART 조회에 실패했을 수 있습니다."}), 400
        return jsonify(result)

    return jsonify({"error": f"unknown section: {section}"}), 400


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
