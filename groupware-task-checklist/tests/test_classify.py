from datetime import date

from core.classify import (
    NEXT_WEEK,
    OVERDUE,
    THIS_WEEK,
    TODAY,
    bucket_label,
    classify_date,
    classify_tasks,
    days_label,
    group_by_bucket,
    ordered_buckets,
    simplified_sections,
)
from core.models import Task


def test_overdue():
    assert classify_date(date(2026, 7, 3), date(2026, 7, 8)) == OVERDUE


def test_today():
    assert classify_date(date(2026, 7, 8), date(2026, 7, 8)) == TODAY


def test_this_week():
    # 7/8 수요일 기준 이번주는 7/6(월)~7/12(일)
    assert classify_date(date(2026, 7, 10), date(2026, 7, 8)) == THIS_WEEK
    assert classify_date(date(2026, 7, 12), date(2026, 7, 8)) == THIS_WEEK


def test_next_week():
    assert classify_date(date(2026, 7, 13), date(2026, 7, 8)) == NEXT_WEEK
    assert classify_date(date(2026, 7, 19), date(2026, 7, 8)) == NEXT_WEEK


def test_month_bucket_beyond_next_week():
    assert classify_date(date(2026, 8, 1), date(2026, 7, 8)) == "MONTH:2026-08"
    assert classify_date(date(2026, 12, 25), date(2026, 7, 8)) == "MONTH:2026-12"


def test_bucket_label():
    assert bucket_label(OVERDUE) == "기한 지남"
    assert bucket_label("MONTH:2026-08") == "2026년 8월"


def test_days_label():
    run = date(2026, 7, 8)
    assert days_label(date(2026, 7, 3), run) == "5일 지남"
    assert days_label(date(2026, 7, 8), run) == "오늘"
    assert days_label(date(2026, 7, 10), run) == "D-2"


def test_ordered_buckets_includes_months_sorted():
    run = date(2026, 7, 8)
    tasks = [
        Task(source="mail", folder="f", title="a", due_date=date(2026, 9, 1)),
        Task(source="mail", folder="f", title="b", due_date=date(2026, 8, 1)),
        Task(source="mail", folder="f", title="c", due_date=date(2026, 7, 8)),
    ]
    classify_tasks(tasks, run)
    groups = group_by_bucket(tasks)
    order = ordered_buckets(groups)
    assert order == [TODAY, "MONTH:2026-08", "MONTH:2026-09"]


def test_simplified_sections_merges_weekly_and_monthly():
    run = date(2026, 7, 8)  # 수요일
    tasks = [
        Task(source="mail", folder="f", title="지남건", due_date=date(2026, 7, 3)),
        Task(source="mail", folder="f", title="오늘건", due_date=date(2026, 7, 8)),
        Task(source="mail", folder="f", title="이번주건", due_date=date(2026, 7, 10)),
        Task(source="mail", folder="f", title="차주건", due_date=date(2026, 7, 14)),
        Task(source="mail", folder="f", title="8월건", due_date=date(2026, 8, 1)),
        Task(source="mail", folder="f", title="9월건", due_date=date(2026, 9, 1)),
    ]
    classify_tasks(tasks, run)
    groups = group_by_bucket(tasks)
    sections = simplified_sections(groups)

    labels = [label for label, _ in sections]
    assert labels == ["기한 지남", "오늘 (일간)", "주간 (이번주~차주)", "월간"]

    weekly_titles = [t.title for label, tasks in sections if label == "주간 (이번주~차주)" for t in tasks]
    assert weekly_titles == ["이번주건", "차주건"]

    monthly_titles = [t.title for label, tasks in sections if label == "월간" for t in tasks]
    assert monthly_titles == ["8월건", "9월건"]


def test_simplified_sections_empty_when_no_tasks():
    groups = group_by_bucket([])
    assert simplified_sections(groups) == []
