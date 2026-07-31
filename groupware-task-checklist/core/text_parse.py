"""메일/전자결재 상세 화면 텍스트에서 '보낸사람', '제목' 같은 헤더 정보를 뽑아낸다.

정확한 화면 구조를 모르기 때문에, 그룹웨어/메일 화면에서 흔히 쓰이는 라벨 단어를
정규식으로 찾는 방식이다 (예: "보낸사람 : 홍길동" / "기안자: 홍길동").
못 찾으면 None 을 반환하고, 호출하는 쪽에서 목록 행 텍스트 등으로 대체한다.
"""

from __future__ import annotations

import re
from typing import List, Optional

SENDER_LABELS = ["보낸\\s*사람", "발신자", "기안자", "상신자", "작성자", "신청자", "From"]
RECEIVER_LABELS = ["받는\\s*사람", "수신자", "결재자", "To"]
CC_LABELS = ["참조", "Cc", "CC"]
SUBJECT_LABELS = ["제\\s*목", "문서명", "건\\s*명", "Subject"]
FORM_TYPE_LABELS = ["양식명", "문서종류", "기안종류", "서식명", "결재종류"]

# 받는사람/참조는 여러 명이 콤마로 나열되는 경우가 많아서(예: "권윤, Yong Seok Kwon (LeeKo)")
# 발신자/제목보다 넉넉하게 잡는다.
_MAX_LEN = 60
_MAX_LEN_LIST = 200

# 이메일 본문 안에 '인용된 이전 메일(전달/회신 히스토리)' 이 시작되는 지점을 찾는 패턴.
# 인용문 안의 "내일"/"오늘" 같은 상대 표현이 현재 메일 기준으로 잘못 해석되거나,
# 인용문 안의 "보낸 사람:" 이 실제 발신자보다 먼저 잡혀버리는 오탐을 막기 위해,
# 이 지점 이후는 통째로 잘라내고 그 앞부분(현재 메일 작성자가 실제로 쓴 부분)만 본다.
_QUOTE_MARKER_RE = re.compile(
    r"^[ \t]*(-{3,}\s*Original Message\s*-{3,}|_{10,}|보낸\s*사람\s*[:：]|발신\s*[:：]|"
    r"From\s*[:：]|보낸\s*날짜\s*[:：]|Sent\s*[:：])",
    re.IGNORECASE | re.MULTILINE,
)


def strip_quoted_reply(text: str) -> str:
    """본문에서 인용된 이전 메일(전달/회신 히스토리) 부분을 잘라내고 앞부분만 반환한다.

    맨 앞부터 바로 인용 마커로 시작하는 경우(잘못 감지했을 가능성)에는 원본을 그대로 둔다.
    """
    if not text:
        return text
    m = _QUOTE_MARKER_RE.search(text)
    if m and m.start() > 0:
        return text[: m.start()]
    return text


def _search_first(text: str, labels: List[str], max_len: int = _MAX_LEN) -> Optional[str]:
    if not text:
        return None
    for label in labels:
        m = re.search(rf"{label}\s*[:：]\s*(.+)", text)
        if not m:
            # 콜론 없이 '레이블   값'(표 형태 상세화면 - 탭/2칸 이상 공백/줄바꿈으로 구분)
            # 형태도 시도한다. 예: "보낸 사람        Tae Yong Kim (LeeKo)"
            m = re.search(rf"{label}(?:[ \t]{{2,}}|\t|\n)\s*(.+)", text)
        if not m:
            continue
        val = m.group(1).splitlines()[0].strip()
        # 표 형태 텍스트에서 다음 컬럼까지 같이 잡히는 경우가 많아, 공백 2칸 이상/탭을 컬럼 구분으로 보고 자른다.
        val = re.split(r"\t|\s{2,}", val)[0].strip()
        if val:
            return val[:max_len]
    return None


def parse_sender(text: str) -> Optional[str]:
    return _search_first(text, SENDER_LABELS)


def parse_receiver(text: str) -> Optional[str]:
    return _search_first(text, RECEIVER_LABELS, max_len=_MAX_LEN_LIST)


def parse_cc(text: str) -> Optional[str]:
    """참조(Cc)로 들어간 사람 목록을 반환한다 (여러 명이면 콤마로 나열된 문자열 그대로)."""
    return _search_first(text, CC_LABELS, max_len=_MAX_LEN_LIST)


def parse_subject(text: str) -> Optional[str]:
    return _search_first(text, SUBJECT_LABELS)


def parse_form_type(text: str) -> Optional[str]:
    return _search_first(text, FORM_TYPE_LABELS)


def is_cc_only(my_name: str, receiver_field: Optional[str], cc_field: Optional[str]) -> bool:
    """이 메일이 '나에게 직접 요청된 것'이 아니라 참조(Cc)로만 걸린 것인지 판단한다.

    받는사람(To) 필드를 정확히 못 읽은 경우(정보 부족)에는 잘못 걸러내는 것보다
    보여주는 쪽이 안전하므로 False(=참조만은 아님, 즉 계속 보여줌)를 반환한다.
    """
    if not my_name or not receiver_field or not cc_field:
        return False
    return my_name in cc_field and my_name not in receiver_field
