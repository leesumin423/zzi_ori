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
SUBJECT_LABELS = ["제\\s*목", "문서명", "건\\s*명", "Subject"]
FORM_TYPE_LABELS = ["양식명", "문서종류", "기안종류", "서식명", "결재종류"]

_MAX_LEN = 60


def _search_first(text: str, labels: List[str]) -> Optional[str]:
    if not text:
        return None
    for label in labels:
        m = re.search(rf"{label}\s*[:：]\s*(.+)", text)
        if not m:
            continue
        val = m.group(1).splitlines()[0].strip()
        # 표 형태 텍스트에서 다음 컬럼까지 같이 잡히는 경우가 많아, 공백 2칸 이상/탭을 컬럼 구분으로 보고 자른다.
        val = re.split(r"\t|\s{2,}", val)[0].strip()
        if val:
            return val[:_MAX_LEN]
    return None


def parse_sender(text: str) -> Optional[str]:
    return _search_first(text, SENDER_LABELS)


def parse_receiver(text: str) -> Optional[str]:
    return _search_first(text, RECEIVER_LABELS)


def parse_subject(text: str) -> Optional[str]:
    return _search_first(text, SUBJECT_LABELS)


def parse_form_type(text: str) -> Optional[str]:
    return _search_first(text, FORM_TYPE_LABELS)
