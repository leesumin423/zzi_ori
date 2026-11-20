# -*- coding: utf-8 -*-
"""
개인 자산 대시보드 (급여 · 미국주식 · 연금/ISA ETF · 배당 · 복지기금 대출)

수기 엑셀 3종을 읽어서
  - 서울외국환중개 매매기준율(연말/분기말/오늘)을 자동으로 받아오고
  - 보유 수량 × 종가(Yahoo Finance, 국내는 네이버 보조)로 평가액을 자동 계산하고
  - 최근 12개월 주당배당금 × 수량으로 예상 배당을 자동 계산하고
  - 연말 스냅샷끼리 비교해 '내 돈 납입 / 주가 효과 / 환율 효과 / 대출 상환'으로
    자산 증가분을 분해하고, 종목별 연말 평가 수익률을 계산합니다.

실행
  python asset_dashboard.py                 → 로컬 서버(http://127.0.0.1:8765) + 브라우저 자동 열기
  python asset_dashboard.py --static 파일.html → 데이터가 담긴 단일 HTML 파일로 저장

엑셀 파일은 ./data 폴더에 넣어두면 내용(시트 이름)으로 자동 구분합니다.
  - 암호가 걸린 파일            → 미국포트폴리오(미국주식_*, 매수일지, 배당시트 …)
  - '복지기금' 시트가 있는 파일   → 대출
  - '소급분' 행이 있는 파일      → 급여

보안
  - 비밀번호는 실행할 때 화면에서 입력받거나(입력 내용 표시 안 됨) 환경변수
    ASSET_XLSX_PASSWORD 로만 받습니다. 어떤 파일에도 저장하지 않습니다.
  - 암호 해제는 메모리에서만 하며, 해제된 엑셀을 디스크에 쓰지 않습니다.
  - 서버는 127.0.0.1(내 PC)에서만 열립니다.
  - data/, cache/, output/ 폴더는 .gitignore 로 커밋되지 않습니다.
"""
import argparse
import datetime as dt
import getpass
import io
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl 이 필요합니다:  pip install openpyxl msoffcrypto-tool")
try:
    import msoffcrypto
except ImportError:
    msoffcrypto = None

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
CACHE_DIR = os.path.join(BASE, "cache")
OVERLAY_PATH = os.path.join(DATA_DIR, "내종목_수정.json")
TX_PATH = os.path.join(DATA_DIR, "업데이트기록.json")      # 엑셀 이후 새로 입력하는 매수·매도·배당·급여·대출상환
TICKER_PATH = os.path.join(DATA_DIR, "종목코드.json")
TEMPLATE = os.path.join(BASE, "dashboard.html")
UA = {"User-Agent": "Mozilla/5.0 (asset-dashboard)"}

US_WITHHOLD = 0.15     # 미국 배당 원천징수
KR_WITHHOLD = 0.154    # 국내 배당소득세(일반계좌 기준)

# 엑셀에 적힌 종목명 → 티커 (미국: AAPL, 국내: 6자리 코드).
# 개인 보유 목록이 공개 저장소에 올라가지 않도록 코드에는 비워 두고,
# data/종목코드.json ({"종목명": "티커"}) 에서 읽는다. 화면의 '티커' 칸에서 고치면 자동 저장된다.
DEFAULT_TICKERS = {}


def norm(name):
    return re.sub(r"\s+", " ", str(name or "")).strip().upper()


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def ticker_map():
    m = {norm(k): v for k, v in DEFAULT_TICKERS.items()}
    m.update({norm(k): v for k, v in load_json(TICKER_PATH, {}).items()})
    return m


def is_kr(ticker):
    return bool(ticker) and bool(re.fullmatch(r"[0-9][0-9A-Z]{5}", ticker))


# ─────────────────────────────── 엑셀 읽기 ───────────────────────────────

class FriendlyError(Exception):
    """사용자에게 그대로 보여줄 안내 메시지"""


def ask_password(prompt):
    """비밀번호 입력. 윈도우 검은 창에서는 한 글자마다 * 를 보여줘 입력되는 걸 확인할 수 있게 한다."""
    if os.name == "nt" and sys.stdin.isatty():
        import msvcrt
        print(prompt, end="", flush=True)
        buf = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                print(); return "".join(buf)
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch in ("\x00", "\xe0"):          # 방향키 등 특수키는 무시
                msvcrt.getwch(); continue
            if ch == "\b":
                if buf:
                    buf.pop(); print("\b \b", end="", flush=True)
                continue
            buf.append(ch); print("*", end="", flush=True)
    return getpass.getpass(prompt)


_PASSWORD = None    # 실행 중 메모리에만 보관 (파일에 쓰지 않음). 화면 수정 때마다 다시 묻지 않기 위함.


def open_book(path, password=None):
    global _PASSWORD
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except PermissionError:
        raise FriendlyError(f"'{name}' 파일을 읽을 수 없습니다. 엑셀에서 열려 있으면 닫고 다시 실행해주세요.")
    if raw[:4] == b"\xd0\xcf\x11\xe0":          # 암호화된 OOXML (CDFV2)
        if msoffcrypto is None:
            raise FriendlyError("암호 걸린 엑셀을 열 프로그램이 없습니다. 실행기를 다시 실행하면 자동 설치됩니다.")
        office = msoffcrypto.OfficeFile(io.BytesIO(raw))
        for attempt in range(3):
            pw = password or _PASSWORD or os.environ.get("ASSET_XLSX_PASSWORD")
            if not pw:
                try:
                    pw = ask_password(f"\n'{name}' 비밀번호를 입력하고 Enter (숫자는 키보드 위쪽 줄로): ").strip()
                except EOFError:
                    raise FriendlyError("비밀번호 입력이 중단됐습니다. 실행기를 다시 더블클릭해서 입력해주세요.")
            try:
                office.load_key(password=pw)
                buf = io.BytesIO()
                office.decrypt(buf)                      # 메모리에서만 해제
                buf.seek(0)
                _PASSWORD = pw
                return openpyxl.load_workbook(buf, data_only=True), True
            except Exception:
                password = _PASSWORD = None
                os.environ.pop("ASSET_XLSX_PASSWORD", None)
                print(f"  → 비밀번호가 맞지 않습니다. ({attempt + 1}/3)")
                office = msoffcrypto.OfficeFile(io.BytesIO(raw))
        raise FriendlyError("비밀번호가 3번 틀렸습니다. 실행기를 다시 켜서 입력해주세요.")
    try:
        return openpyxl.load_workbook(io.BytesIO(raw), data_only=True), False
    except Exception:
        raise FriendlyError(f"'{name}' 파일을 엑셀로 읽을 수 없습니다. .xlsx 형식인지 확인해주세요.")


def find_books(paths):
    books = {}
    for p in paths:
        wb, enc = open_book(p)
        names = wb.sheetnames
        if "복지기금" in names:
            books["loan"] = wb
        elif any(n.startswith("미국주식") for n in names):
            books["portfolio"] = wb
        else:
            ws = wb.active
            if any(isinstance(c, str) and "소급" in c for r in ws.iter_rows(values_only=True) for c in r):
                books["salary"] = wb
    missing = [k for k in ("salary", "loan", "portfolio") if k not in books]
    if missing:
        label = {"salary": "급여 엑셀('○○년 소급분' 행이 있는 파일)", "loan": "대출 엑셀('복지기금' 시트가 있는 파일)",
                 "portfolio": "미국포트폴리오 엑셀('미국주식_…' 시트가 있는 파일)"}
        raise FriendlyError("data 폴더에서 다음 엑셀을 찾지 못했습니다:\n  - " + "\n  - ".join(label[m] for m in missing)
                            + "\n  (읽은 파일: " + ", ".join(os.path.basename(p) for p in paths) + ")")
    return books


def parse_salary(wb):
    rows = []
    for r in wb.active.iter_rows(values_only=True):
        if len(r) > 16 and isinstance(r[4], str) and "소급" in r[4] and is_num(r[14]):
            m = re.match(r"(\d{2})", r[4])
            rows.append(dict(year=2000 + int(m.group(1)) if m else None, label=r[4].strip(),
                             promo=(r[3] == "승진"), retro=r[5] or 0, prev=r[10], base=r[11],
                             bonus=r[12] or 0, perf=r[13] or 0, total=r[14], inc=r[15], rate=r[16]))
    return rows


def parse_loans(wb):
    loans = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        principal = rate = None
        for r in rows[:3]:
            for i, c in enumerate(r):
                if c == "원금" and principal is None:
                    principal = next((x for x in r[i + 1:] if is_num(x)), None)
                if c == "금리" and rate is None:
                    rate = next((x for x in r[i + 1:] if is_num(x)), None)
        hdr = next((r for r in rows[:6] if "일자" in r), None)
        if not hdr or not principal:
            continue
        di, ii, pi, bi = hdr.index("일자"), hdr.index("이자"), hdr.index("원금"), hdr.index("잔여원금")
        sched = []
        for r in rows:
            if isinstance(r[di], dt.datetime) and is_num(r[bi]):
                sched.append(dict(d=r[di].strftime("%Y-%m-%d"), interest=round(r[ii] or 0),
                                  principal=round(r[pi] or 0) if sched else 0, bal=round(r[bi])))
        amortizing = any(s["principal"] for s in sched)
        loans.append(dict(name=ws.title, principal=principal, rate=rate, amortizing=amortizing, rows=sched))
    return loans


SHEET_DATE = re.compile(r"\(\s*(\d{2})\s*\.\s*(\d{1,2})\s*\.?\s*(\d{1,2})")


def sheet_name_date(title):
    """'미국주식_25년 2분기말' → 2025-06-30 (시트 이름 우선, 제목의 날짜는 보조)"""
    m = re.search(r"(\d{2})", title)
    if not m:
        return None
    y = 2000 + int(m.group(1))
    for pat, md in ((r"1분기", (3, 31)), (r"2분기|반기", (6, 30)), (r"3분기", (9, 30)),
                    (r"4분기|년\s*말", (12, 31)), (r"(\d{1,2})월\s*말", None)):
        mm = re.search(pat, title)
        if mm:
            if md is None:
                mo = int(mm.group(1)); nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
                return nxt - dt.timedelta(days=1)
            return dt.date(y, *md)
    return None


def parse_us_sheets(wb, tmap):
    """미국주식_* 시트마다 (기준일, 보유종목[증권사·수량·평단], 매도내역, 분산종목 합계)"""
    out = []
    for ws in wb.worksheets:
        if not ws.title.startswith("미국주식_"):
            continue
        rows = list(ws.iter_rows(values_only=True))
        date = sheet_name_date(ws.title)
        for r in ([] if date else rows[:3]):
            for c in r:
                m = SHEET_DATE.search(str(c or ""))
                if m:
                    date = dt.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    break
            if date:
                break
        if not date:
            continue
        hdr_i = next(i for i, r in enumerate(rows) if "주식명" in r)
        hdr = rows[hdr_i]
        ni, qi = hdr.index("주식명"), hdr.index("주식수")
        ai = hdr.index("평단")
        bi = hdr.index("증권사") if "증권사" in hdr else None
        price_i = next((i for i, c in enumerate(hdr) if isinstance(c, str) and "종가" in c), None)
        dps_i = next((i for i, c in enumerate(hdr) if c == "배당"), None)
        sp_i = hdr.index("분산종목") if "분산종목" in hdr else None
        holdings, sells, spread, section, broker = [], [], [], "hold", None
        for r in rows[hdr_i + 1:]:
            if sp_i is not None and isinstance(r[sp_i], str) and is_num(r[sp_i + 1]):
                spread.append(dict(name=r[sp_i].strip(), qty=r[sp_i + 1], cost=r[sp_i + 2],
                                   brokers=[b.strip() for b in str(r[sp_i + 5] or "").replace(".", ",").split(",") if b.strip()]))
            if r[0] == "매도":
                section = "sell"
            if "합계" in r[:3]:
                if section == "hold":
                    section = "between"
                continue
            if bi is not None and r[bi] and r[bi] != "증권사":
                broker = r[bi]
            if section == "hold" and isinstance(r[ni], str) and is_num(r[qi]) and is_num(r[ai]):
                holdings.append(dict(name=r[ni].strip(), ticker=tmap.get(norm(r[ni])), qty=r[qi],
                                     avg=r[ai], cost=r[qi] * r[ai], broker=broker,
                                     sheetPrice=r[price_i] if price_i is not None and is_num(r[price_i]) else None))
            elif section == "sell" and len(r) > 7 and is_num(r[4]) and is_num(r[5]) and is_num(r[6]):
                nm = r[3] if isinstance(r[3], str) else (sells[-1]["name"] if sells else "?")
                sells.append(dict(name=nm.strip(), ticker=tmap.get(norm(nm)), qty=r[4], buy=r[5], sell=r[6],
                                  pnl=(r[6] - r[5]) * r[4]))
        out.append(dict(sheet=ws.title, date=date.isoformat(), holdings=holdings, sells=sells, spread=spread,
                        realized=round(sum(x["pnl"] for x in sells), 2)))
    out.sort(key=lambda s: s["date"])
    return out


def reconcile_spread(sheet, tmap):
    """'분산종목' 합계가 메인 목록보다 많으면 그 차이를 '미배분 계좌' 보유로 추가"""
    extra = []
    by_t = defaultdict(float)
    listed_brokers = defaultdict(set)
    for h in sheet["holdings"]:
        by_t[h["ticker"] or norm(h["name"])] += h["qty"]
        listed_brokers[h["ticker"] or norm(h["name"])].add(h["broker"])
    alias = load_json(TICKER_PATH, {})
    for sp in sheet.get("spread", []):
        t = tmap.get(norm(sp["name"])) or alias.get(sp["name"]) or sp["name"].upper()
        diff = sp["qty"] - by_t.get(t, 0)
        if diff > 0.01:
            others = [b for b in sp["brokers"] if b not in listed_brokers.get(t, set())]
            avg = sp["cost"] / sp["qty"] if sp["qty"] else 0
            nm = next((h["name"] for h in sheet["holdings"] if h["ticker"] == t), sp["name"])
            extra.append(dict(name=nm, ticker=t, qty=diff, avg=avg, cost=diff * avg,
                              broker="미배분(" + ",".join(others) + ")" if others else "미배분", unassigned=True))
    return extra


def parse_kr_journals(wb, tmap):
    """YY년_매수일지: 월별 매수액, 연말 '투자처 별 잔고'(계좌별 보유), 매도 내역"""
    years = {}
    for ws in wb.worksheets:
        m = re.match(r"(\d{2})년_매수일지", ws.title)
        if not m:
            continue
        year = 2000 + int(m.group(1))
        rows = list(ws.iter_rows(values_only=True))
        top, hdr = rows[0], rows[1]
        ci = [i for i, c in enumerate(hdr) if c == "종목명"][-1]               # 종합누계 블록
        bi = next((i for i, c in enumerate(top) if isinstance(c, str) and "투자처 별" in c), None)
        monthly = [0.0] * 12
        buys = defaultdict(lambda: [0.0, 0.0])
        for r in rows[2:]:
            if isinstance(r[2], dt.datetime) and is_num(r[3]) and is_num(r[5]):
                monthly[r[2].month - 1] += r[5]
                b = buys[norm(r[0])]
                b[0] += r[3]; b[1] += r[5]
        holdings = []
        if bi is not None:                                                     # 계좌별
            for r in rows[2:]:
                if isinstance(r[bi], str) and r[bi + 1] and is_num(r[bi + 2]) and is_num(r[bi + 3]):
                    holdings.append(dict(name=r[bi].strip(), ticker=tmap.get(norm(r[bi])), broker=str(r[bi + 1]).strip(),
                                         qty=r[bi + 2], cost=r[bi + 3], avg=r[bi + 3] / r[bi + 2] if r[bi + 2] else 0))
        sells, mode = [], "hold"
        for r in rows[2:]:
            c = r[ci] if len(r) > ci else None
            if c == "매도 내역":
                mode = "sell"; continue
            if not holdings and mode == "hold" and isinstance(c, str) and is_num(r[ci + 1]) and is_num(r[ci + 2]):
                holdings.append(dict(name=c.strip(), ticker=tmap.get(norm(c)), broker="미상", qty=r[ci + 1],
                                     cost=r[ci + 2], avg=r[ci + 2] / r[ci + 1] if r[ci + 1] else 0))
            elif mode == "sell" and isinstance(c, str) and c != "종목명" and is_num(r[ci + 1]) and is_num(r[ci + 2]):
                price = r[ci + 4] if is_num(r[ci + 4]) else 0
                sells.append(dict(name=c.strip(), ticker=tmap.get(norm(c)), qty=r[ci + 1], cost=r[ci + 2],
                                  pnl=price * r[ci + 1] - r[ci + 2]))
        years[year] = dict(monthly=[round(x) for x in monthly], holdings=holdings,
                           buys={k: v for k, v in buys.items()}, sells=sells)
    return years


def parse_dividends(wb):
    """배당시트(YY) 오른쪽 '종합 배당소득' 블록: 월별 실수령(기록)"""
    out = {}
    for ws in wb.worksheets:
        m = re.match(r"배당시트\((\d{2})\)", ws.title)
        if not m:
            continue
        rows = list(ws.iter_rows(values_only=True))
        col = next((i for r in rows[:3] for i, c in enumerate(r) if c == "종합 배당소득"), None)
        if col is None:
            continue
        subtotals, fx_total, total = [], None, None
        for r in rows:
            k = r[col]
            vals = [x if is_num(x) else 0 for x in r[col + 2: col + 14]]
            if k == "소계":
                subtotals.append(vals)
            elif k == "환산 계":
                fx_total = vals
            elif k == "합계":
                total = vals
        if total:
            out[2000 + int(m.group(1))] = dict(us=fx_total or [0] * 12,
                                               kr=subtotals[1] if len(subtotals) > 1 else [0] * 12,
                                               total=total)
    return out


def parse_networth(wb):
    if "자산트래킹" not in wb.sheetnames:
        return []
    return [dict(m=r[0], v=r[1]) for r in wb["자산트래킹"].iter_rows(min_row=3, max_row=14, values_only=True)
            if r[0] and is_num(r[1]) and r[1] > 0]


# ─────────────────────────────── 시장 데이터 ───────────────────────────────

class Market:
    """서울외국환중개 환율 + Yahoo/네이버 시세. cache/ 에 저장해 재실행을 빠르게."""

    def __init__(self, offline=False):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.offline = offline
        self.fx_cache = load_json(os.path.join(CACHE_DIR, "fx_smbs.json"), {})
        self.lock = threading.Lock()
        self.charts = {}

    def _get(self, url, timeout=20):
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    # 서울외국환중개 매매기준율. 휴일이면 직전 영업일로 거슬러 올라감.
    def fx(self, date):
        if isinstance(date, str):
            date = dt.date.fromisoformat(date)
        today = dt.date.today()
        for back in range(0, 10):
            d = (date - dt.timedelta(days=back)).isoformat()
            if d in self.fx_cache and self.fx_cache[d]:
                return self.fx_cache[d], d
            if self.offline:
                continue
            try:
                txt = self._get(f"http://www.smbs.biz/Flash/TodayExRate_flash.jsp?tr_date={d}", 15).decode("euc-kr", "ignore")
                m = re.search(r"USD=([0-9,\.]+)", txt)
                val = float(m.group(1).replace(",", "")) if m else None
            except Exception:
                val = None
            with self.lock:
                if val or d < today.isoformat():   # 과거 휴일은 '없음'으로 기억, 오늘은 재시도
                    self.fx_cache[d] = val
                    save_json(os.path.join(CACHE_DIR, "fx_smbs.json"), self.fx_cache)
            if val:
                return val, d
        return None, None

    def chart(self, ticker):
        """일별 종가(분할 반영), 분할·배당 이력, 현재가"""
        if not ticker:
            return None
        if ticker in self.charts:
            return self.charts[ticker]
        path = os.path.join(CACHE_DIR, f"chart_{ticker}.json")
        cached = load_json(path, None)
        if cached and (self.offline or cached.get("fetched") == dt.date.today().isoformat()):
            self.charts[ticker] = cached
            return cached
        res = None
        if not self.offline:
            symbols = [ticker + ".KS", ticker + ".KQ"] if is_kr(ticker) else [ticker]
            p2 = int(time.time()) + 86400
            for sym in symbols:
                try:
                    raw = json.loads(self._get(
                        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
                        f"?period1=1672531200&period2={p2}&interval=1d&events=div%7Csplit"))
                    r = (raw.get("chart", {}).get("result") or [None])[0]
                    if not r or not r.get("timestamp"):
                        continue
                    closes = r["indicators"]["quote"][0]["close"]
                    days = [dt.datetime.fromtimestamp(t + (r["meta"].get("gmtoffset", dt.timezone.utc) or 0)).date().isoformat()
                            for t in r["timestamp"]]
                    ev = r.get("events", {})
                    res = dict(
                        symbol=sym, currency=r["meta"].get("currency"),
                        name=r["meta"].get("longName") or r["meta"].get("shortName") or sym,
                        price=r["meta"].get("regularMarketPrice"),
                        days=days, closes=closes,
                        splits=sorted([(dt.datetime.fromtimestamp(s["date"], dt.timezone.utc).date().isoformat(),
                                        s["numerator"] / s["denominator"]) for s in ev.get("splits", {}).values()]),
                        divs=sorted([(dt.datetime.fromtimestamp(s["date"], dt.timezone.utc).date().isoformat(), s["amount"])
                                     for s in ev.get("dividends", {}).values()]))
                    break
                except Exception:
                    continue
            if res is None and is_kr(ticker):        # Yahoo에 없는 국내 종목 → 네이버 현재가만
                try:
                    d = json.loads(self._get(f"https://polling.finance.naver.com/api/realtime/domestic/stock/{ticker}"))["datas"][0]
                    res = dict(symbol=ticker, currency="KRW", name=d["stockName"],
                               price=float(d["closePrice"].replace(",", "")), days=[], closes=[], splits=[], divs=[])
                except Exception:
                    pass
            if res:
                res["fetched"] = dt.date.today().isoformat()
                save_json(path, res)
        res = res or cached
        self.charts[ticker] = res
        return res

    @staticmethod
    def _split_factor(c, date):
        """분할 전 날짜의 종가를 '그 당시 주식 수' 기준 가격으로 되돌리는 배수.
        Yahoo가 분할을 과거 가격 일부에만 반영한 경우가 있어, 시계열 안에서
        분할 비율만큼 가격이 튀는 지점(미반영 경계)을 찾아 그 이전은 원가격으로 본다."""
        import math
        f = 1.0
        days, closes = c.get("days", []), c.get("closes", [])
        for d, ratio in c.get("splits", []):
            if d < date or ratio <= 0:          # 분할 당일 기록은 분할 전 수량으로 본다
                continue
            target = math.log(1 / ratio)
            boundary, prev = None, None
            for i in range(len(days)):
                if closes[i] is None:
                    continue
                if prev is not None and days[i] <= d and abs(math.log(closes[i] / closes[prev]) - target) < 0.35:
                    boundary = days[i]
                prev = i
            if boundary and date < boundary:
                continue                         # 이 구간은 분할 미반영 원가격
            f *= ratio
        return f

    def close_on(self, ticker, date):
        """date 이전 마지막 종가를 '그 당시 주식 수' 기준(분할 전 가격)으로 반환"""
        c = self.chart(ticker)
        if not c or not c.get("days"):
            return None
        date = date if isinstance(date, str) else date.isoformat()
        idx = None
        for i, d in enumerate(c["days"]):
            if d <= date and c["closes"][i] is not None:
                idx = i
            elif d > date:
                break
        if idx is None:
            return None
        return c["closes"][idx] * self._split_factor(c, c["days"][idx])

    def shares_factor(self, ticker, recorded):
        """recorded 날짜에 적어둔 수량을 오늘 기준 수량으로 바꾸는 배수 (그 뒤 분할·병합 반영)"""
        c = self.chart(ticker) if ticker else None
        f = 1.0
        for d, ratio in (c or {}).get("splits", []):
            if d >= recorded and ratio > 0:
                f *= ratio
        return f

    def ttm_dps(self, ticker, asof=None):
        """최근 12개월 주당 배당금(현재 주식 수 기준)과 연간 지급 횟수"""
        c = self.chart(ticker)
        if not c:
            return 0.0, 0
        asof = asof or dt.date.today()
        start = (asof - dt.timedelta(days=365)).isoformat()
        ev = [(d, a) for d, a in c.get("divs", []) if start < d <= asof.isoformat()]
        return sum(a for _, a in ev), len(ev)


# ─────────────────────────────── 계산 ───────────────────────────────

    # ── 네이버 실시간 시세 (국내: 6자리 코드, 미국: 로이터 코드 KO / AAPL.O / SGOV.K …)
    def naver_code(self, ticker):
        if is_kr(ticker):
            return ticker
        path = os.path.join(CACHE_DIR, "naver_codes.json")
        codes = load_json(path, {})
        if ticker in codes:
            return codes[ticker]
        found = None
        for suf in ("", ".O", ".K", ".N", ".A"):
            try:
                d = json.loads(self._get(f"https://api.stock.naver.com/stock/{ticker}{suf}/basic", 8))
                if d.get("reutersCode") and d.get("closePrice"):
                    found = d["reutersCode"]; break
            except Exception:
                continue
        with self.lock:
            codes = load_json(path, {}); codes[ticker] = found; save_json(path, codes)
        return found

    def live(self, tickers):
        out, kr, us = {}, [], {}
        for t in tickers:
            if not t:
                continue
            if is_kr(t):
                kr.append(t)
            else:
                c = self.naver_code(t)
                if c:
                    us[c] = t

        def num(x):
            try:
                return float(str(x).replace(",", ""))
            except Exception:
                return None

        def take(datas, keyf):
            for d in datas:
                t = keyf(d)
                if not t:
                    continue
                price, chg = num(d.get("closePrice")), num(d.get("compareToPreviousClosePrice"))
                st = (d.get("marketStatus") or "")
                out[t] = dict(price=price, change=chg, rate=num(d.get("fluctuationsRatio")),
                              status=st, at=d.get("localTradedAt") or d.get("localTradedAtFormat"))
        try:
            for i in range(0, len(kr), 40):
                d = json.loads(self._get("https://polling.finance.naver.com/api/realtime/domestic/stock/" + ",".join(kr[i:i + 40]), 10))
                take(d.get("datas", []), lambda x: x.get("itemCode"))
        except Exception:
            pass
        try:
            codes = list(us)
            for i in range(0, len(codes), 40):
                d = json.loads(self._get("https://polling.finance.naver.com/api/realtime/worldstock/stock/" + ",".join(codes[i:i + 40]), 10))
                take(d.get("datas", []), lambda x: us.get(x.get("reutersCode")))
        except Exception:
            pass
        fx = None
        try:
            r = json.loads(self._get("https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_USDKRW", 8))["result"]
            fx = dict(price=num(r["closePrice"]), change=num(r.get("fluctuations")), at=r.get("localTradedAt"), src="하나은행 고시(네이버)")
        except Exception:
            pass
        for t in tickers:                     # 네이버 실패 시 Yahoo 현재가로 대체
            if t and t not in out:
                c = self.chart(t)
                if c and c.get("price") is not None:
                    out[t] = dict(price=c["price"], change=None, rate=None, status="Yahoo", at=c.get("fetched"))
        return dict(prices=out, fx=fx, at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# ─────────────────────────────── 계산 ───────────────────────────────

def hkey(broker, ticker, name):
    return f"{broker or '미상'}|{ticker or 'NAME:' + norm(name)}"


def merge_rows(items):
    """같은 계좌·같은 종목은 합치기 (수량 합, 평단 가중평균)"""
    out = {}
    for h in items:
        k = hkey(h.get("broker"), h.get("ticker"), h["name"])
        o = out.setdefault(k, dict(key=k, name=h["name"], ticker=h.get("ticker"), broker=h.get("broker") or "미상",
                                   qty=0.0, cost=0.0, sheetPrice=None, unassigned=h.get("unassigned", False)))
        o["qty"] += h["qty"]
        o["cost"] += h.get("cost") if h.get("cost") is not None else h["qty"] * h.get("avg", 0)
        o["sheetPrice"] = o["sheetPrice"] or h.get("sheetPrice")
    for o in out.values():
        o["avg"] = o["cost"] / o["qty"] if o["qty"] else 0
    return list(out.values())


def value_rows(mkt, items, date, market):
    """보유 목록을 date 기준 종가로 평가. 시세가 없으면 시트 종가, 그것도 없으면 원금으로 둠(표시)."""
    rows = []
    for h in merge_rows(items):
        price = mkt.close_on(h["ticker"], date) if h["ticker"] else None
        src = "시세"
        if price is None and h.get("sheetPrice"):
            price, src = h["sheetPrice"], "시트"
        value = price * h["qty"] if price is not None else h["cost"]
        if price is None:
            src = "원금"
        rows.append(dict(h, market=market, price=price, value=value, src=src))
    return rows


def realized_by_year(us_sheets, kr_years):
    """연도별·종목별 실현손익 (미국 USD, 국내 KRW)"""
    out = defaultdict(lambda: defaultdict(float))
    for s in us_sheets:
        y = s["date"][:4]
        for x in s["sells"]:
            out[y]["US|" + (x["ticker"] or norm(x["name"]))] += x["pnl"]
    for y, j in kr_years.items():
        for x in j["sells"]:
            out[str(y)]["KR|" + (x["ticker"] or norm(x["name"]))] += x["pnl"]
    return {y: dict(v) for y, v in out.items()}


# ─────────────────────────── 업데이트 기록 (엑셀 이후) ───────────────────────────

def load_tx():
    tx = [t for t in load_json(TX_PATH, []) if isinstance(t, dict) and t.get("date") and t.get("type")]
    return sorted(tx, key=lambda t: (t["date"], t.get("id", 0)))


def apply_trades(base, txs, upto, tmap):
    """엑셀 기준 보유(base)에 upto 날짜까지의 매수·매도 기록을 순서대로 적용"""
    import copy
    rows = copy.deepcopy(base)
    realized = defaultdict(lambda: defaultdict(float))
    notes = []
    for t in txs:
        if t["date"] > upto or t["type"] not in ("buy", "sell"):
            continue
        ticker = (t.get("ticker") or "").strip().upper() or tmap.get(norm(t.get("name"))) or None
        broker = (t.get("broker") or "미상").strip()
        qty, price = float(t.get("qty") or 0), float(t.get("price") or 0)
        market = "KR" if is_kr(ticker) else "US"
        same = [r for r in rows if r["broker"] == broker and ((ticker and r.get("ticker") == ticker) or
                                                             (not ticker and norm(r["name"]) == norm(t.get("name"))))]
        if t["type"] == "buy":
            if same:
                r = same[0]
                cost = r["qty"] * r["avg"] + qty * price
                r["qty"] += qty; r["avg"] = cost / r["qty"] if r["qty"] else 0
                r["cost"] = cost; r["source"] = "기록"
            else:
                name = t.get("name") or ticker
                rows.append(dict(key=hkey(broker, ticker, name), name=name, ticker=ticker, broker=broker, market=market,
                                 qty=qty, avg=price, cost=qty * price, source="기록", sheetPrice=None, unassigned=False))
        else:
            if not same:
                same = [r for r in rows if ticker and r.get("ticker") == ticker and r["qty"] > 0]
            if not same:
                notes.append(f"{t['date']} 매도 {t.get('name') or ticker}: 보유 내역을 찾지 못함"); continue
            r = same[0]
            q = min(qty, r["qty"])
            if q < qty:
                notes.append(f"{t['date']} 매도 {r['name']}: 보유 {r['qty']:g}주보다 많아 {q:g}주만 반영")
            realized[t["date"][:4]][r["market"] + "|" + (r.get("ticker") or norm(r["name"]))] += (price - r["avg"]) * q
            r["qty"] -= q; r["cost"] = r["qty"] * r["avg"]; r["source"] = "기록"
    rows = [r for r in rows if r["qty"] > 1e-9]
    return rows, realized, notes


def apply_other_tx(txs, salary, loans, divs, mkt):
    """급여 변경 · 대출 상환 · 배당 수령 기록을 엑셀 데이터에 덧붙임"""
    for t in txs:
        d = t["date"]; y, m = int(d[:4]), int(d[5:7])
        if t["type"] == "salary":
            base_, bonus, perf = (float(t.get(k) or 0) for k in ("base", "bonus", "perf"))
            prev = salary[-1]["total"] if salary else 0
            total = base_ + bonus + perf
            salary.append(dict(year=y, label=f"{d[2:4]}년 {m}월 변경", promo=bool(t.get("promo")), retro=float(t.get("retro") or 0),
                               prev=prev, base=base_, bonus=bonus, perf=perf, total=total, inc=total - prev,
                               rate=(total / prev - 1) if prev else 0, fromTx=True))
        elif t["type"] == "repay":
            amt = float(t.get("amount") or 0)
            ln = next((l for l in loans if l["name"] == t.get("loan")), None)
            if not ln or amt <= 0:
                continue
            before = [r for r in ln["rows"] if r["d"] <= d]
            bal = before[-1]["bal"] if before else ln["principal"]
            after = [r for r in ln["rows"] if r["d"] > d]
            for r in after:
                r["bal"] = max(0, r["bal"] - amt)
                if r["bal"] == 0:
                    r["principal"] = 0; r["interest"] = 0
            ln["rows"].append(dict(d=d, interest=0, principal=round(amt), bal=round(max(0, bal - amt)), fromTx=True))
            ln["rows"].sort(key=lambda r: r["d"])
        elif t["type"] == "div":
            amt = float(t.get("amount") or 0)
            if t.get("currency", "KRW") == "USD":
                fx, _ = mkt.fx(d); amt_krw, part = amt * (fx or 0), "us"
            else:
                amt_krw, part = amt, "kr"
            dv = divs.setdefault(y, dict(us=[0] * 12, kr=[0] * 12, total=[0] * 12))
            dv[part][m - 1] += amt_krw; dv["total"][m - 1] += amt_krw


def build(paths, offline=False, mkt=None):
    tmap = ticker_map()
    books = find_books(paths)
    mkt = mkt or Market(offline=offline)
    mkt.charts = {}
    today = dt.date.today()
    pf = books["portfolio"]

    salary = parse_salary(books["salary"])
    loans = parse_loans(books["loan"])
    us_sheets = parse_us_sheets(pf, tmap)
    kr_years = parse_kr_journals(pf, tmap)
    divs = parse_dividends(pf)
    networth = parse_networth(pf)
    overlay = load_json(OVERLAY_PATH, {"edits": {}, "added": [], "removed": []})
    txs = load_tx()
    for t in txs:
        if t.get("ticker"):
            t["ticker"] = str(t["ticker"]).strip().upper()

    tickers = {h["ticker"] for s in us_sheets for h in s["holdings"] if h["ticker"]}
    tickers |= {h["ticker"] for y in kr_years.values() for h in y["holdings"] if h["ticker"]}
    tickers |= {a["ticker"] for a in overlay.get("added", []) if a.get("ticker")}
    tickers |= {e["ticker"] for e in overlay.get("edits", {}).values() if e.get("ticker")}
    tickers |= {t["ticker"] for t in txs if t.get("ticker")}
    ths = [threading.Thread(target=mkt.chart, args=(t,)) for t in tickers]
    [t.start() for t in ths]; [t.join() for t in ths]
    fx_today, fx_today_d = mkt.fx(today)
    apply_other_tx(txs, salary, loans, divs, mkt)

    # 미국 분기 시트별 평가
    us_hist = []
    for s in us_sheets:
        items = s["holdings"] + reconcile_spread(s, tmap)
        rows = value_rows(mkt, items, s["date"], "US")
        fx, fx_d = mkt.fx(s["date"])
        us_hist.append(dict(sheet=s["sheet"], date=s["date"], cost=sum(r["cost"] for r in rows),
                            value=sum(r["value"] for r in rows),
                            unpriced=sum(r["cost"] for r in rows if r["src"] == "원금"),
                            fx=fx, fxDate=fx_d, realized=s["realized"]))

    # 국내 연말 보유: 각 연도 '투자처 별 잔고'. 첫해 직전 연말은 역산.
    kr_snap = {f"{y}-12-31": j["holdings"] for y, j in kr_years.items()}
    if kr_years:
        y0 = min(kr_years); j = kr_years[y0]
        tot = defaultdict(lambda: [0.0, 0.0, None, None])
        for h in j["holdings"]:
            t = tot[norm(h["name"])]; t[0] += h["qty"]; t[1] += h["cost"]; t[2] = h["name"]; t[3] = h["ticker"]
        for x in j["sells"]:
            t = tot[norm(x["name"])]; t[0] += x["qty"]; t[1] += x["cost"]; t[2] = t[2] or x["name"]; t[3] = t[3] or x["ticker"]
        prev = []
        for k, (q, c, nm, tk) in tot.items():
            b = j["buys"].get(k, [0, 0])
            q2, c2 = q - b[0], c - b[1]
            if q2 > 0.0001:
                prev.append(dict(name=nm, ticker=tk, broker="(역산)", qty=q2, cost=c2))
        kr_snap[f"{y0 - 1}-12-31"] = prev

    # 현재 보유 = 최신 미국 시트(+미배분) + 최신 국내 계좌별 잔고 + 화면 수정분
    latest_us = us_sheets[-1] if us_sheets else None
    base = []
    if latest_us:
        for r in merge_rows(latest_us["holdings"] + reconcile_spread(latest_us, tmap)):
            f = mkt.shares_factor(r["ticker"], latest_us["date"])
            if abs(f - 1) > 1e-9:                # 시트 작성 후 분할/병합 → 오늘 기준 수량으로
                r["splitNote"] = f"분할·병합 반영 {r['qty']:g}주 → {r['qty'] * f:g}주"
                r["qty"] *= f; r["avg"] /= f
            base.append(dict(r, market="US"))
    if kr_years:
        base += [dict(r, market="KR") for r in merge_rows(kr_years[max(kr_years)]["holdings"])]
    edits, removed = overlay.get("edits", {}), set(overlay.get("removed", []))
    current = []
    for h in base:
        h["source"] = "엑셀"
        if h["key"] in removed:
            continue
        e = edits.get(h["key"])
        if e:
            h.update({k: v for k, v in e.items() if k in ("qty", "avg", "ticker", "name", "broker")})
            h["source"] = "수정"; h["unassigned"] = h["unassigned"] and "broker" not in e
        h["cost"] = h["qty"] * h["avg"]
        current.append(h)
    for a in overlay.get("added", []):
        if a.get("key") in removed:
            continue
        current.append(dict(a, cost=a["qty"] * a["avg"], source="추가", sheetPrice=None, unassigned=False))
    excel_base = current                                   # 엑셀 + 화면 수정 (업데이트 기록 적용 전)
    current, tx_realized, tx_notes = apply_trades(excel_base, txs, today.isoformat(), tmap)
    for h in current:
        enrich_quote(mkt, h)

    # 스냅샷: 각 연말 + 오늘
    us_by_date = {s["date"]: s for s in us_sheets}
    dates = sorted(d for d in set(kr_snap) | {s["date"] for s in us_sheets if s["date"].endswith("12-31")}
                   if d < today.isoformat())
    base_date = latest_us["date"] if latest_us else "0000"
    dates = [d for d in dates if d <= base_date]
    # 엑셀 이후 지나간 연말은 '엑셀 기준 + 그 날까지의 업데이트 기록'으로 자동 생성
    for y in range(int(base_date[:4]) if latest_us else today.year, today.year):
        d = f"{y}-12-31"
        if d > base_date:
            dates.append(d)
    snaps = []
    for d in dates:
        if d > base_date:
            h_at, _, _ = apply_trades(excel_base, txs, d, tmap)
            snaps.append(snapshot(mkt, d, f"{d[:4]}년말", [h for h in h_at if h["market"] == "US"],
                                  [h for h in h_at if h["market"] == "KR"], loans, salary, divs))
            continue
        us_s = us_by_date.get(d)
        snaps.append(snapshot(mkt, d, f"{d[:4]}년말",
                              us_s["holdings"] + reconcile_spread(us_s, tmap) if us_s else None,
                              kr_snap.get(d), loans, salary, divs))
    snaps.append(snapshot(mkt, today.isoformat(), "현재",
                          [h for h in current if h["market"] == "US"],
                          [h for h in current if h["market"] == "KR"], loans, salary, divs))

    return dict(
        generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), today=today.isoformat(),
        fxToday=fx_today, fxTodayDate=fx_today_d,
        salary=salary, loans=loans, dividends={str(k): v for k, v in divs.items()},
        krMonthly={str(y): j["monthly"] for y, j in kr_years.items()},
        usHistory=us_hist, current=current, snapshots=snaps, networth=networth,
        realized=merge_realized(realized_by_year(us_sheets, kr_years), tx_realized),
        tax=dict(us=US_WITHHOLD, kr=KR_WITHHOLD), overlay=overlay,
        tx=txs, txNotes=tx_notes, baseDate=base_date,
    )


def merge_realized(a, b):
    out = {y: dict(v) for y, v in a.items()}
    for y, v in b.items():
        for k, x in v.items():
            out.setdefault(y, {})[k] = out.get(y, {}).get(k, 0) + x
    return out


def enrich_quote(mkt, h):
    c = mkt.chart(h.get("ticker")) if h.get("ticker") else None
    h["price"] = c.get("price") if c else None
    h["priceSrc"] = "시세" if h["price"] is not None else ("시트" if h.get("sheetPrice") else "없음")
    if h["price"] is None and h.get("sheetPrice"):
        h["price"] = h["sheetPrice"]
    dps, n = mkt.ttm_dps(h.get("ticker")) if c else (0.0, 0)
    h["ttmDps"], h["divCount"] = dps, n
    h["quoteName"] = c.get("name") if c else None
    return h


def snapshot(mkt, date, label, us_items, kr_items, loans, salary, divs):
    year = int(date[:4])
    fx, fx_d = mkt.fx(date)
    us = value_rows(mkt, us_items, date, "US") if us_items is not None else None
    kr = value_rows(mkt, kr_items, date, "KR") if kr_items is not None else None
    debt, debt_rows = 0, []
    for ln in loans:
        bal = 0 if (ln["rows"] and ln["rows"][0]["d"] > date) else ln["principal"]
        for r in ln["rows"]:
            if r["d"] <= date:
                bal = r["bal"]
        debt += bal; debt_rows.append(dict(name=ln["name"], bal=bal))
    sal = [s for s in salary if s["year"] and s["year"] <= year]
    monthly = sal[-1]["total"] if sal else (salary[0]["prev"] if salary else None)
    return dict(date=date, label=label, fx=fx, fxDate=fx_d, us=us, kr=kr, debt=debt, debtRows=debt_rows,
                monthlyPay=monthly, divReceived=sum(divs[year]["total"]) if year in divs else None)


class App:
    def __init__(self, paths, offline=False):
        self.paths, self.offline = paths, offline
        self.data, self.lock = None, threading.Lock()
        self.mkt = Market(offline=offline)
        self.last_seen = time.time()
        self.server = None

    def refresh(self):
        with self.lock:
            self.data = build(self.paths, self.offline, self.mkt)
        return self.data


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            b = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            app.last_seen = time.time()
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path == "/api/ping":
                return self._send(200, '{"ok":true,"app":"asset-dashboard"}')
            if u.path in ("/", "/index.html"):
                with open(TEMPLATE, encoding="utf-8") as f:
                    return self._send(200, f.read().replace("__DATA__", "null"), "text/html; charset=utf-8")
            if u.path == "/api/data":
                return self._send(200, json.dumps(app.data, ensure_ascii=False, default=str))
            if u.path == "/api/live":
                ts = sorted({h["ticker"] for h in app.data["current"] if h.get("ticker")})
                return self._send(200, json.dumps(app.mkt.live(ts), ensure_ascii=False))
            if u.path == "/api/quote":
                t = (q.get("ticker") or [""])[0].strip().upper()
                h = enrich_quote(app.mkt, dict(ticker=t))
                fx, _ = app.mkt.fx(dt.date.today())
                return self._send(200, json.dumps(dict(ok=h["price"] is not None, ticker=t, name=h["quoteName"],
                                                       price=h["price"], ttmDps=h["ttmDps"], divCount=h["divCount"],
                                                       market="KR" if is_kr(t) else "US", fx=fx), ensure_ascii=False))
            return self._send(404, '{"error":"not found"}')

        def do_POST(self):
            app.last_seen = time.time()
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/shutdown":
                self._send(200, '{"ok":true}')
                threading.Thread(target=app.server.shutdown, daemon=True).start()
                return
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/overlay":
                ov = dict(edits=body.get("edits", {}), added=body.get("added", []), removed=body.get("removed", []))
                save_json(OVERLAY_PATH, ov)
                tm = load_json(TICKER_PATH, {})
                for a in ov["added"]:
                    if a.get("name") and a.get("ticker"):
                        tm[a["name"]] = a["ticker"]
                for k, e in ov["edits"].items():
                    if e.get("ticker") and e.get("name"):
                        tm[e["name"]] = e["ticker"]
                save_json(TICKER_PATH, tm)
                return self._send(200, json.dumps(app.refresh(), ensure_ascii=False, default=str))
            if u.path == "/api/tx":
                txs = [t for t in body.get("tx", []) if isinstance(t, dict) and t.get("date") and t.get("type")]
                save_json(TX_PATH, txs)
                return self._send(200, json.dumps(app.refresh(), ensure_ascii=False, default=str))
            if u.path == "/api/refresh":
                return self._send(200, json.dumps(app.refresh(), ensure_ascii=False, default=str))
            return self._send(404, '{"error":"not found"}')
    return H


IDLE_LIMIT = 10 * 60      # 브라우저 탭을 닫고 이 시간(초) 동안 요청이 없으면 자동 종료


def running_on(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return b"asset-dashboard" in r.read()
    except Exception:
        return False


def free_port(start):
    import socket
    for port in range(start, start + 10):
        with socket.socket() as sk:
            if os.name != "nt":
                sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # 방금 끈 서버의 TIME_WAIT 무시
            try:
                sk.bind(("127.0.0.1", port)); return port
            except OSError:
                continue
    raise FriendlyError("대시보드를 열 포트를 찾지 못했습니다. PC를 재시작한 뒤 다시 실행해주세요.")


def serve(paths, port, offline):
    """백그라운드(창 없음)에서 도는 대시보드 서버"""
    app = App(paths, offline)
    app.refresh()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    app.server = srv

    def idle_watch():
        while True:
            time.sleep(30)
            if time.time() - app.last_seen > IDLE_LIMIT:
                srv.shutdown(); return
    threading.Thread(target=idle_watch, daemon=True).start()
    srv.serve_forever()


def launch_background(paths, port, offline):
    """비밀번호를 확인한 뒤 창 없는 서버를 띄우고, 준비되면 브라우저를 연다. 검은 창은 닫힌다."""
    import subprocess
    exe = sys.executable
    flags = 0
    if os.name == "nt":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            exe = w
        flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    env = dict(os.environ)
    if _PASSWORD:
        env["ASSET_XLSX_PASSWORD"] = _PASSWORD          # 자식 프로세스 메모리로만 전달 (파일·명령줄에 남기지 않음)
    os.makedirs(os.path.join(BASE, "output"), exist_ok=True)
    log = os.path.join(BASE, "output", "오류기록.txt")
    if os.path.exists(log):
        os.remove(log)
    cmd = [exe, os.path.abspath(__file__), "--serve", "--port", str(port)] + (["--offline"] if offline else []) + paths
    kw = dict(env=env, cwd=BASE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        kw["creationflags"] = flags
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    print("엑셀 읽고 환율·시세 받는 중… (처음엔 1~2분 걸릴 수 있어요)", end="", flush=True)
    for _ in range(300):
        if running_on(port):
            break
        if proc.poll() is not None:
            msg = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
            last = [l for l in msg.strip().splitlines() if l.strip()][-1:] or ["알 수 없는 오류"]
            raise FriendlyError("대시보드 서버가 시작되지 못했습니다: " + last[0] + f"\n  자세한 내용: {log}")
        time.sleep(1); print(".", end="", flush=True)
    else:
        raise FriendlyError("대시보드 준비가 너무 오래 걸립니다. 인터넷 연결을 확인하고 다시 실행해주세요.")
    url = f"http://127.0.0.1:{port}/"
    print(f"\n\n대시보드를 열었습니다: {url}\n이 창은 곧 닫힙니다. 끌 때는 대시보드 오른쪽 위 [종료] 버튼을 누르세요.")
    webbrowser.open(url)
    time.sleep(3)


def main():
    ap = argparse.ArgumentParser(description="개인 자산 대시보드")
    ap.add_argument("files", nargs="*", help="엑셀 파일들 (생략하면 ./data 폴더의 .xlsx 전부)")
    ap.add_argument("--static", metavar="OUT.html", help="서버 없이 데이터가 담긴 HTML 한 장으로 저장")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--offline", action="store_true", help="인터넷 조회 없이 cache 폴더 값만 사용")
    ap.add_argument("--foreground", action="store_true", help="검은 창에서 서버를 계속 실행(창을 닫으면 종료)")
    ap.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)   # 내부용: 창 없는 서버
    a = ap.parse_args()

    if a.serve:
        serve(a.files, a.port, a.offline)
        return

    if not a.static:                                  # 이미 켜져 있으면 브라우저만 연다
        live_port = next((pt for pt in range(a.port, a.port + 10) if running_on(pt)), None)
        if live_port:
            print("이미 실행 중인 대시보드를 엽니다.")
            webbrowser.open(f"http://127.0.0.1:{live_port}/")
            time.sleep(2)
            return

    os.makedirs(DATA_DIR, exist_ok=True)
    paths = a.files or sorted(os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
                              if f.lower().endswith((".xlsx", ".xlsm")) and not f.startswith("~$"))
    if not paths:
        raise FriendlyError(f"엑셀 파일이 없습니다.\n  아래 폴더에 급여·대출·미국포트폴리오 엑셀 3개를 넣고 다시 실행해주세요:\n  {DATA_DIR}")
    paths = [os.path.abspath(p) for p in paths]
    print("읽을 엑셀:", ", ".join(os.path.basename(p) for p in paths))

    if a.static:
        data = build(paths, a.offline)
        with open(TEMPLATE, encoding="utf-8") as f:
            html = f.read().replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/"))
        os.makedirs(os.path.dirname(os.path.abspath(a.static)), exist_ok=True)
        with open(a.static, "w", encoding="utf-8") as f:
            f.write(html)
        print("저장:", a.static)
        return

    find_books(paths)                                 # 여기서 비밀번호 확인·엑셀 구성 점검 (실패하면 바로 안내)
    port = free_port(a.port)
    if a.foreground:
        print("엑셀 읽고 환율·시세 받는 중…")
        url = f"http://127.0.0.1:{port}/"
        threading.Timer(3, lambda: webbrowser.open(url)).start()
        print(f"대시보드: {url}  (이 창을 닫으면 종료)")
        serve(paths, port, a.offline)
        return
    launch_background(paths, port, a.offline)


def run():
    try:
        main()
    except FriendlyError as e:
        if "--serve" in sys.argv:
            os.makedirs(os.path.join(BASE, "output"), exist_ok=True)
            with open(os.path.join(BASE, "output", "오류기록.txt"), "w", encoding="utf-8") as f:
                f.write(str(e))
        else:
            print("\n[안내] " + str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        os.makedirs(os.path.join(BASE, "output"), exist_ok=True)
        if sys.stdout is None or "--serve" in sys.argv:
            with open(os.path.join(BASE, "output", "오류기록.txt"), "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
            sys.exit(1)
        log = os.path.join(BASE, "output", "오류기록.txt")
        with open(log, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        traceback.print_exc()
        print(f"\n[오류] 예상하지 못한 문제가 생겼습니다. 위 내용(또는 {log})을 캡처해서 알려주세요.")
        sys.exit(1)


if __name__ == "__main__":
    run()
