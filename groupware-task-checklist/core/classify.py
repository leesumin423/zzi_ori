from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

from .models import Task

OVERDUE = "OVERDUE"
TODAY = "TODAY"
THIS_WEEK = "THIS_WEEK"
NEXT_WEEK = "NEXT_WEEK"
LATER = "LATER"
UNKNOWN = "UNKNOWN"

BUCKET_LABELS = {
    OVERDUE: "🔴 기한 지남",
    TODAY: "🟠 오늘",
    THIS_WEEK: "🟡 이번주",
    NEXT_WEEK: "🔵 차주",
    LATER: "⚪ 그 이후",
    UNKNOWN: "❓ 날짜 미확인",
}

# 팝업에 기본으로 노출할 버킷 순서 (LATER/UNKNOWN 은 기본적으로 숨김)
DEFAULT_VISIBLE_BUCKETS = [OVERDUE, TODAY, THIS_WEEK, NEXT_WEEK]


def week_range(d: date, weeks_ahead: int = 0) -> Tuple[date, date]:
    monday = d - timedelta(days=d.weekday()) + timedelta(weeks=weeks_ahead)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def classify_date(due_date: date, run_date: date) -> str:
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
    return LATER


def classify_tasks(tasks: List[Task], run_date: date) -> List[Task]:
    for t in tasks:
        t.bucket = classify_date(t.due_date, run_date)
    return tasks


def group_by_bucket(tasks: List[Task]) -> dict:
    groups: dict = {b: [] for b in BUCKET_LABELS}
    for t in tasks:
        groups.setdefault(t.bucket, []).append(t)
    for bucket_tasks in groups.values():
        bucket_tasks.sort(key=lambda t: (t.due_date or date.max, t.title))
    return groups
