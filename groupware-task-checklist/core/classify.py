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


def _sort_tasks(tasks: List[Task]) -> List[Task]:
    return sorted(tasks, key=lambda t: (t.due_date or date.max, t.title))


def simplified_sections(groups: dict) -> List[Tuple[str, List[Task]]]:
    """오늘(일간) / 주간(이번주+차주 합침) / 월간(그 이후 전부 합침) 3단으로 간략하게 묶는다.

    지난 기한(OVERDUE)은 더 이상 실행할 수 없는 항목이라 팝업에는 표시하지 않는다
    (완료 체크 대상에서만 빠질 뿐, 분류 자체는 계속 계산되어 groups 에는 남아있다).

    이번주/차주를 따로 안 보고 "이번주에 챙겨야 할지, 다음주까지 여유가 있는지" 정도만
    한눈에 보고 싶을 때를 위한 요약 뷰. 세밀한 버킷(THIS_WEEK/NEXT_WEEK/MONTH:*)이 필요하면
    ordered_buckets() + bucket_label() 조합을 그대로 쓰면 된다.
    """
    sections: List[Tuple[str, List[Task]]] = []

    today = groups.get(TODAY, [])
    if today:
        sections.append(("오늘 (일간)", _sort_tasks(today)))

    weekly = groups.get(THIS_WEEK, []) + groups.get(NEXT_WEEK, [])
    if weekly:
        sections.append(("주간 (이번주~차주)", _sort_tasks(weekly)))

    monthly: List[Task] = []
    for key, tasks in groups.items():
        if key.startswith(MONTH_PREFIX):
            monthly.extend(tasks)
    if monthly:
        sections.append(("월간", _sort_tasks(monthly)))

    return sections
