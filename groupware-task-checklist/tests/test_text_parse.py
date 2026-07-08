from core.text_parse import parse_form_type, parse_receiver, parse_sender, parse_subject


def test_parse_mail_header():
    text = (
        "받은메일함\n"
        "제목 : 월간보고서 회신 요청\n"
        "보낸사람 : 홍길동  2026-07-01 10:23\n"
        "받는사람 : 이수민\n"
        "본문 내용입니다..."
    )
    assert parse_subject(text) == "월간보고서 회신 요청"
    assert parse_sender(text) == "홍길동"
    assert parse_receiver(text) == "이수민"


def test_parse_approval_header():
    text = "문서명: 출장 신청서\n기안자: 김철수\n결재자: 박부장"
    assert parse_subject(text) == "출장 신청서"
    assert parse_sender(text) == "김철수"


def test_parse_form_type():
    text = "양식명 : 법인인감신청서\n작성자: 김철수"
    assert parse_form_type(text) == "법인인감신청서"


def test_parse_returns_none_when_missing():
    assert parse_sender("아무 정보도 없는 텍스트") is None
    assert parse_subject("") is None
