import os
import re
import json
from datetime import date, datetime, time as dtime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)

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
def fetch_theme_change(no: int) -> str:
    """테마 그룹 페이지에서 전일대비 등락률 반환"""
    url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        raw = r.content.decode('utf-8', errors='replace')
        soup = BeautifulSoup(raw, 'html.parser')
        first_num = soup.select_one('td.number span')
        if first_num:
            txt = first_num.get_text(strip=True)
            arrow = '\u2191' if txt.startswith('+') else '\u2193'
            return f"{txt} {arrow}"
        return 'N/A'
    except Exception as e:
        return f'N/A ({e})'

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

    # 3) 상장주식수 + 52주 최고/최저: main 페이지에서 함께 추출 (UTF-8)
    shares = 0
    high_52w = None
    low_52w  = None
    try:
        main_url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        mr = requests.get(main_url, headers=HEADERS, timeout=10)
        mr.encoding = 'utf-8'  # 핵심 수정: euc-kr -> utf-8
        msoup = BeautifulSoup(mr.text, 'html.parser')

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

    # 장중 고점/저점이 종가보다 훨씬 튀면(되돌림이 있었으면) 그 흐름을 덧붙임
    peak_pct, direction = (high_pct, 'up') if abs(high_pct) >= abs(low_pct) else (low_pct, 'down')
    mid_desc = ''
    if abs(peak_pct - close_pct) >= 6.0:
        if direction == 'up':
            mid_desc = f", 장중 한때 {day['high']:,}원까지 상승({peak_pct:+.1f}%)했으나 상승분을 상당 부분 반납"
        else:
            mid_desc = f", 장중 한때 {day['low']:,}원까지 하락({peak_pct:+.1f}%)했으나 낙폭을 일부 만회"

    close_desc = f"종가 {day['close']:,}원({close_pct:+.2f}%)에 마감"
    parts = [f"{day['date']} {open_desc}{mid_desc}, {close_desc}"]

    h = hist_by_date.get(day['date'])
    if h:
        flow_sentence = _flow_summary_sentence(h, price_up=(close_pct > 0) if close_pct != 0 else None)
        if flow_sentence:
            parts.append(flow_sentence)

    matched = _find_related_news(news, day['date'], display_name)
    if matched:
        parts.append(f"관련 기사 「{matched['title']}」({matched['date']})")
    else:
        parts.append("최근 관련 뉴스는 확인되지 않음")

    return '. '.join(parts)

# 종목 공시 게시판에는 "단기과열종목 지정"처럼 반복적으로 계속 연장되는 조치와
# "매매거래정지및정지해제"처럼 당일 안에 풀리는 일회성 조치가 섞여 있어서,
# 여러 날 이어지는 실제 거래정지의 '진짜' 원인을 공시 제목만 보고 자동으로
# 정확히 골라내기 어렵다 (예: 2026.07 동양 거래정지는 실제로는 액면(주식)병합이
# 원인이었는데, 자동 매칭은 시점상 가장 최근인 "단기과열종목 지정 연장" 공시를
# 잘못 골랐었음). 그래서 확인된 사유를 알고 있으면 여기에 직접 적어두면
# 자동 추정보다 우선해서 코멘트에 반영된다. 종목코드를 키로 사용.
MANUAL_HALT_REASONS = {
    "001520": "액면(주식)병합에 따른 매매거래정지",
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
        result = [{"name": name, "change": fetch_theme_change(no)} for name, no in THEMES]
        return jsonify(result)

    if section == 'companies':
        COMPANIES = {
            "동양":         "001520",
            "유진기업":     "023410",
            "유진투자증권": "001200",
            "YTN":          "040300",
            "티엑스알로보틱스": "484810",
        }
        CAPITAL = {
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
            d['capital_billion'] = CAPITAL.get(name, '0')
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
        # 자본금(억원): DART 공시 기준 납입자본금 (보통주 × 5,000원 액면가 / 1억)
        CEMENT_CAPITAL = {
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
            d['capital_billion'] = CEMENT_CAPITAL.get(name, '0')
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

    return jsonify({"error": f"unknown section: {section}"}), 400


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
