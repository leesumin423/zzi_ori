from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

from .models import Task

OVERDUE = "OVERDUE"
TODAY = "TODAY"
THIS_WEEK = "THIS_WEEK"
NEXT_WEEK = "NEXT_WEEK"
UNKNOWN = "UNKNOWN"
MONTH_PREFIX = "MONTH:"

_STATIC_LABELS = {
    OVERDUE: "기한 지남",
    TODAY: "오늘",
    THIS_WEEK: "이번주",
    NEXT_WEEK: "차주",
    UNKNOWN: "날짜 미확인",
}

# 팝업에서 이 순서대로 먼저 보여준다. 차주 이후(MONTH:*) 항목은 이 뒤에 날짜순으로 붙는다.
FIXED_BUCKET_ORDER = [OVERDUE, TODAY, THIS_WEEK, NEXT_WEEK]


def week_range(d: date, weeks_ahead: int = 0) -> Tuple[date, date]:
    monday = d - timedelta(days=d.weekday()) + timedelta(weeks=weeks_ahead)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def classify_date(due_date: date, run_date: date) -> str:
    """차주까지는 요일 단위(지남/오늘/이번주/차주)로, 그 이후는 월 단위(MONTH:YYYY-MM)로 분류한다."""
    if due_date is None:
        return UNKNOWN
    if due_date < run_date:
        return OVERDUE
    if due_date == run_date:
        return TODAY
    this_mon, this_sun = week_range(run_date, 0)
    if this_mon <= due_date <= this_sun:
        return THIS_WEEK
    next_mon, next_sun = week_range(run_date, 1)
    if next_mon <= due_date <= next_sun:
        return NEXT_WEEK
    return f"{MONTH_PREFIX}{due_date.strftime('%Y-%m')}"


def bucket_label(bucket: str) -> str:
    if bucket in _STATIC_LABELS:
        return _STATIC_LABELS[bucket]
    if bucket.startswith(MONTH_PREFIX):
        y, m = bucket[len(MONTH_PREFIX):].split("-")
        return f"{y}년 {int(m)}월"
    return bucket


def days_label(due_date: date, run_date: date) -> str:
    if due_date is None:
        return ""
    delta = (due_date - run_date).days
    if delta < 0:
        return f"{-delta}일 지남"
    if delta == 0:
        return "오늘"
    return f"D-{delta}"


def classify_tasks(tasks: List[Task], run_date: date) -> List[Task]:
    for t in tasks:
        t.bucket = classify_date(t.due_date, run_date)
    return tasks


def group_by_bucket(tasks: List[Task]) -> dict:
    groups: dict = {b: [] for b in FIXED_BUCKET_ORDER}
    for t in tasks:
        groups.setdefault(t.bucket, []).append(t)
    for bucket_tasks in groups.values():
        bucket_tasks.sort(key=lambda t: (t.due_date or date.max, t.title))
    return groups


def ordered_buckets(groups: dict) -> List[str]:
    """팝업에 표시할 버킷 순서: 지남→오늘→이번주→차주→월별(가까운 순)→날짜미확인."""
    order = [b for b in FIXED_BUCKET_ORDER if groups.get(b)]
    month_keys = sorted(k for k in groups if k.startswith(MONTH_PREFIX) and groups[k])
    order += month_keys
    if groups.get(UNKNOWN):
        order.append(UNKNOWN)
    return order
