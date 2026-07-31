from datetime import date

from core.date_extract import extract_dates, guess_doc_date


def test_user_example_md_paren_weekday():
    anchor = date(2026, 7, 1)  # 메일이 7/1(수)에 왔다고 가정
    text = "월간보고서 7/3(금) 오전까지 회신 바랍니다."
    matches = extract_dates(text, anchor)
    assert len(matches) == 1
    assert matches[0].due_date == date(2026, 7, 3)


def test_korean_month_day_form():
    anchor = date(2026, 7, 1)
    text = "자료는 7월 10일까지 제출 부탁드립니다."
    matches = extract_dates(text, anchor)
    assert matches[0].due_date == date(2026, 7, 10)


def test_full_ymd_form():
    anchor = date(2026, 1, 1)
    text = "계약서는 2026-07-15까지 회신 바랍니다."
    matches = extract_dates(text, anchor)
    assert matches[0].due_date == date(2026, 7, 15)


def test_today_tomorrow():
    anchor = date(2026, 7, 8)
    assert extract_dates("오늘까지 완료해주세요.", anchor)[0].due_date == date(2026, 7, 8)
    assert extract_dates("내일까지 회신 바랍니다.", anchor)[0].due_date == date(2026, 7, 9)
    assert extract_dates("모레까지 제출 바랍니다.", anchor)[0].due_date == date(2026, 7, 10)


def test_ikil_alias_for_tomorrow():
    anchor = date(2026, 7, 8)  # 수요일
    m = extract_dates("익일까지 회신 부탁드립니다.", anchor)
    assert m[0].due_date == date(2026, 7, 9)


def test_business_days_skips_weekend():
    # 목요일(7/9)에 온 메일, "1영업일 오전내" -> 다음 영업일인 금요일(7/10)
    anchor = date(2026, 7, 9)
    m = extract_dates("1영업일 오전내 회신 부탁드립니다.", anchor)
    assert m[0].due_date == date(2026, 7, 10)

    # 금요일(7/10)에 온 메일, "1영업일" -> 주말(토/일) 건너뛰고 월요일(7/13)
    anchor2 = date(2026, 7, 10)
    m2 = extract_dates("1영업일 이내 회신 바랍니다.", anchor2)
    assert m2[0].due_date == date(2026, 7, 13)

    # 3영업일 - 수(7/8) 기준 목,금,월 -> 7/13
    anchor3 = date(2026, 7, 8)
    m3 = extract_dates("3영업일 이내 제출 부탁드립니다.", anchor3)
    assert m3[0].due_date == date(2026, 7, 13)


def test_this_week_next_week_weekday():
    anchor = date(2026, 7, 8)  # 수요일
    m = extract_dates("이번주 금요일까지 회신 바랍니다.", anchor)
    assert m[0].due_date == date(2026, 7, 10)  # 이번주 금
    m = extract_dates("차주 월요일까지 제출 바랍니다.", anchor)
    assert m[0].due_date == date(2026, 7, 13)  # 다음주 월


def test_bare_weekday_rolls_to_next_week_if_passed():
    anchor = date(2026, 7, 9)  # 목요일
    # 이번주 화요일(7/7)은 이미 지났으므로 다음주 화요일로 해석
    m = extract_dates("화요일까지 회신 바랍니다.", anchor)
    assert m[0].due_date == date(2026, 7, 14)


def test_this_week_next_week_no_weekday():
    anchor = date(2026, 7, 8)  # 수요일, 이번주 월=7/6, 일=7/12
    m = extract_dates("이번주까지 완료 부탁드립니다.", anchor)
    assert m[0].due_date == date(2026, 7, 12)
    m = extract_dates("차주까지 제출 바랍니다.", anchor)
    assert m[0].due_date == date(2026, 7, 19)


def test_month_end():
    anchor = date(2026, 7, 8)
    m = extract_dates("월말까지 마감입니다.", anchor)
    assert m[0].due_date == date(2026, 7, 31)


def test_within_n_days():
    anchor = date(2026, 7, 8)
    m = extract_dates("3일 이내 회신 바랍니다.", anchor)
    assert m[0].due_date == date(2026, 7, 11)


def test_ignores_sentences_without_deadline_keyword():
    anchor = date(2026, 7, 8)
    text = "작성일: 7/1 참고용 문서입니다."
    assert extract_dates(text, anchor) == []


def test_year_rollover_past():
    # 12월에 온 메일에서 "1월 5일까지"라고 하면 다음 해로 보정
    anchor = date(2026, 12, 20)
    m = extract_dates("1월 5일까지 제출 바랍니다.", anchor)
    assert m[0].due_date == date(2027, 1, 5)


def test_guess_doc_date_list_row():
    fallback = date(2026, 7, 8)
    assert guess_doc_date("보낸사람: 홍길동 2026-07-01 10:23 월간보고서", fallback) == date(2026, 7, 1)
    assert guess_doc_date("07/02 김철수 결재상신", fallback) == date(2026, 7, 2)
    assert guess_doc_date("아무 날짜도 없는 텍스트", fallback) == fallback


def test_multiple_sentences_multiple_dates():
    anchor = date(2026, 7, 1)
    text = (
        "1차 자료는 7/3(금)까지 회신 바랍니다.\n"
        "최종본은 7월 10일까지 제출 부탁드립니다."
    )
    matches = extract_dates(text, anchor)
    dates = sorted(m.due_date for m in matches)
    assert dates == [date(2026, 7, 3), date(2026, 7, 10)]
