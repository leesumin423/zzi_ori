from core.text_parse import (
    is_cc_only,
    parse_cc,
    parse_form_type,
    parse_receiver,
    parse_sender,
    parse_subject,
    strip_quoted_reply,
)


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


def test_parse_sender_table_layout_without_colon():
    # 표 형태 상세화면에서는 콜론 없이 탭/여러 칸 공백으로 구분되는 경우가 많다.
    text = "제목\t\tRE: 임시주총 소집통지 관련 질의\n보낸 사람\t\tTae Yong Kim (LeeKo)\t\n받는 사람 \t\t\n권윤"
    assert parse_sender(text) == "Tae Yong Kim (LeeKo)"


def test_strip_quoted_reply_removes_forwarded_history():
    text = (
        "안녕하세요, 내일까지 회신 부탁드립니다.\n\n"
        "보낸 사람: Yong Seok Kwon (LeeKo) <yongseok.kwon@leeko.com>\n"
        "Sent: Tuesday, June 23, 2026 10:50 AM\n"
        "To: 이수민\n"
        "Subject: RE: 예전 메일 - 내일까지 회신 부탁드립니다\n\n"
        "예전 내용..."
    )
    stripped = strip_quoted_reply(text)
    assert "안녕하세요, 내일까지 회신 부탁드립니다." in stripped
    assert "Yong Seok Kwon" not in stripped
    assert "예전 내용" not in stripped


def test_strip_quoted_reply_keeps_original_when_no_marker():
    text = "그냥 평범한 본문입니다."
    assert strip_quoted_reply(text) == text


def test_parse_cc_multiple_names():
    text = "받는 사람 \t\t\n권윤, Yong Seok Kwon (LeeKo)\n\n참조\t\t\n전장규, 이수민, Hee Woong Lee (LeeKo)"
    assert parse_receiver(text) == "권윤, Yong Seok Kwon (LeeKo)"
    assert parse_cc(text) == "전장규, 이수민, Hee Woong Lee (LeeKo)"


def test_is_cc_only_true_when_in_cc_not_receiver():
    receiver = "권윤, Yong Seok Kwon (LeeKo)"
    cc = "전장규, 이수민, Hee Woong Lee (LeeKo)"
    assert is_cc_only("이수민", receiver, cc) is True


def test_is_cc_only_false_when_directly_addressed():
    receiver = "이수민"
    cc = "전장규"
    assert is_cc_only("이수민", receiver, cc) is False


def test_is_cc_only_false_when_fields_missing():
    # 정보가 부족하면(못 읽었으면) 잘못 걸러내는 것보다 보여주는 쪽이 안전하다.
    assert is_cc_only("이수민", None, "전장규, 이수민") is False
    assert is_cc_only("이수민", "권윤", None) is False
    assert is_cc_only("", "권윤", "이수민") is False
