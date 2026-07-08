"""메일/전자결재 본문 텍스트에서 '마감일/기한' 표현을 찾아 실제 날짜로 변환한다.

전략:
  1. 텍스트를 문장 단위로 쪼갠다.
  2. 마감을 암시하는 키워드(까지/마감/제출/회신/바랍니다 등)가 포함된 문장만 본다.
     (그냥 날짜가 언급됐다고 전부 마감일로 잡으면 "작성일: 7/1"류 오탐이 많아진다.)
  3. 그 문장 안에서 날짜 패턴을 찾아 anchor_date(메일 수신일 등 기준일)를 기준으로
     절대 날짜(date)로 변환한다.

anchor_date는 "이번주 금요일", "차주 월요일", "내일" 같은 상대 표현을 해석하는 기준이 된다.
(메일이 보내진 날짜를 기준으로 해석하는 게 자연스럽다.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

DEADLINE_KEYWORDS = [
    "까지", "마감", "제출", "회신", "바랍니다", "부탁드립니다", "부탁드려요",
    "완료해", "완료 부탁", "기한", "데드라인", "회신 요청", "제출 요청",
    "보고 바랍니다", "송부 바랍니다", "확인 바랍니다", "결재 요청",
]

_WEEKDAY_MAP = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_WEEKDAY_CHARS = "".join(_WEEKDAY_MAP.keys())


@dataclass
class DateMatch:
    due_date: date
    matched_text: str
    sentence: str


def _split_sentences(text: str) -> List[str]:
    text = text.replace("\r\n", "\n")
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _clamp_month_rollover(anchor: date, candidate: date) -> date:
    """연도 없는 날짜(예: 7/3)가 anchor 기준 너무 먼 과거/미래로 튀면 연도를 보정한다."""
    delta = (candidate - anchor).days
    if delta < -300:
        candidate = candidate.replace(year=candidate.year + 1)
    elif delta > 300:
        candidate = candidate.replace(year=candidate.year - 1)
    return candidate


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _week_day_date(anchor: date, weekday_idx: int, which: str) -> date:
    monday = anchor - timedelta(days=anchor.weekday())
    if which == "next":
        monday += timedelta(days=7)
    return monday + timedelta(days=weekday_idx)


def _nearest_upcoming_weekday(anchor: date, weekday_idx: int) -> date:
    this_week = _week_day_date(anchor, weekday_idx, "this")
    if this_week >= anchor:
        return this_week
    return _week_day_date(anchor, weekday_idx, "next")


def _resolve_matches(anchor: date, sentence: str) -> List[DateMatch]:
    results: List[DateMatch] = []

    def add(d: Optional[date], matched: str):
        if d is not None:
            results.append(DateMatch(due_date=d, matched_text=matched, sentence=sentence))

    # 1) YYYY.MM.DD / YYYY-MM-DD / YYYY년 MM월 DD일
    for m in re.finditer(r"(20\d{2})\s?[.\-년]\s?(\d{1,2})\s?[.\-월]\s?(\d{1,2})\s?일?", sentence):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        add(_safe_date(y, mo, d), m.group(0))
    if results:
        return results

    # 2) M월 D일 (+ 요일 옵션)
    for m in re.finditer(r"(\d{1,2})\s?월\s?(\d{1,2})\s?일", sentence):
        mo, d = int(m.group(1)), int(m.group(2))
        cand = _safe_date(anchor.year, mo, d)
        if cand:
            add(_clamp_month_rollover(anchor, cand), m.group(0))
    if results:
        return results

    # 3) M/D(요일) 또는 M.D 또는 M-D  (연도 없음, 슬래시/점/하이픈)
    for m in re.finditer(
        r"(\d{1,2})\s?[/.]\s?(\d{1,2})\s?(?:\(\s?([월화수목금토일])\s?\))?", sentence
    ):
        mo, d = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        cand = _safe_date(anchor.year, mo, d)
        if cand:
            add(_clamp_month_rollover(anchor, cand), m.group(0))
    if results:
        return results

    # 4) 오늘/내일/모레
    if re.search(r"(오늘|금일|당일)", sentence):
        add(anchor, re.search(r"(오늘|금일|당일)", sentence).group(0))
    if re.search(r"(내일|명일)", sentence):
        add(anchor + timedelta(days=1), re.search(r"(내일|명일)", sentence).group(0))
    if re.search(r"모레", sentence):
        add(anchor + timedelta(days=2), "모레")
    if results:
        return results

    # 5) 이번주/차주 + 요일
    m = re.search(rf"(이번\s?주|금주)\s?([{_WEEKDAY_CHARS}])\s?요일?", sentence)
    if m:
        add(_week_day_date(anchor, _WEEKDAY_MAP[m.group(2)], "this"), m.group(0))
    m = re.search(rf"(다음\s?주|차주|담주)\s?([{_WEEKDAY_CHARS}])\s?요일?", sentence)
    if m:
        add(_week_day_date(anchor, _WEEKDAY_MAP[m.group(2)], "next"), m.group(0))
    if results:
        return results

    # 6) 요일만 (예: "금요일까지")
    m = re.search(rf"([{_WEEKDAY_CHARS}])\s?요일\s?까지", sentence)
    if m:
        add(_nearest_upcoming_weekday(anchor, _WEEKDAY_MAP[m.group(1)]), m.group(0))
    if results:
        return results

    # 7) 이번주/차주 끝(주말) - 명시적 요일 없이
    m = re.search(r"(이번\s?주|금주)\s?(까지|중)", sentence)
    if m:
        add(_week_day_date(anchor, 6, "this"), m.group(0))
    m = re.search(r"(다음\s?주|차주|담주)\s?(까지|중)", sentence)
    if m:
        add(_week_day_date(anchor, 6, "next"), m.group(0))
    if results:
        return results

    # 8) 월말
    m = re.search(r"(이번\s?달\s?말|이달\s?말|월말)", sentence)
    if m:
        if anchor.month == 12:
            last_day = date(anchor.year, 12, 31)
        else:
            last_day = date(anchor.year, anchor.month + 1, 1) - timedelta(days=1)
        add(last_day, m.group(0))
    if results:
        return results

    # 9) N일 이내 / N주 이내
    m = re.search(r"(\d{1,2})\s?일\s?(이내|내)", sentence)
    if m:
        add(anchor + timedelta(days=int(m.group(1))), m.group(0))
    m = re.search(r"(\d{1})\s?주(?:일)?\s?(이내|내)", sentence)
    if m:
        add(anchor + timedelta(weeks=int(m.group(1))), m.group(0))
    if results:
        return results

    # 10) D-N
    m = re.search(r"D[-\s]?(\d{1,2})", sentence)
    if m:
        add(anchor + timedelta(days=int(m.group(1))), m.group(0))

    return results


_ABS_DATE_PATTERNS = [
    r"(20\d{2})\s?[.\-년]\s?(\d{1,2})\s?[.\-월]\s?(\d{1,2})\s?일?",
    r"(\d{1,2})\s?월\s?(\d{1,2})\s?일",
    r"(\d{1,2})\s?[/.]\s?(\d{1,2})(?!\d)",
]


def guess_doc_date(text: str, fallback: date) -> date:
    """메일/결재 목록 행 텍스트에서 '문서 날짜'로 보이는 절대 날짜를 하나 찾는다.
    (마감 키워드 없이도 매칭 - 목록 뷰의 날짜 컬럼을 잡기 위함)
    실패하면 fallback을 그대로 반환한다."""
    if not text:
        return fallback
    m = re.search(_ABS_DATE_PATTERNS[0], text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        cand = _safe_date(y, mo, d)
        if cand:
            return cand
    for pat in _ABS_DATE_PATTERNS[1:]:
        m = re.search(pat, text)
        if m:
            mo, d = int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                cand = _safe_date(fallback.year, mo, d)
                if cand:
                    return _clamp_month_rollover(fallback, cand)
    return fallback


def extract_dates(text: str, anchor_date: date) -> List[DateMatch]:
    """텍스트에서 마감일 후보를 모두 찾아 반환한다 (중복 날짜는 제거)."""
    if not text:
        return []
    found: List[DateMatch] = []
    seen_dates = set()
    for sentence in _split_sentences(text):
        if not any(kw in sentence for kw in DEADLINE_KEYWORDS):
            continue
        for match in _resolve_matches(anchor_date, sentence):
            if match.due_date in seen_dates:
                continue
            seen_dates.add(match.due_date)
            found.append(match)
    return found
