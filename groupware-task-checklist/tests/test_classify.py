from datetime import date

from core.classify import (
    NEXT_WEEK,
    OVERDUE,
    THIS_WEEK,
    TODAY,
    LATER,
    classify_date,
)


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


def test_later():
    assert classify_date(date(2026, 8, 1), date(2026, 7, 8)) == LATER
