from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Task:
    """하나의 '마감일이 언급된' 메일/전자결재 항목."""

    source: str  # "mail" | "approval"
    folder: str  # 예: "받은메일함", "부서함-완료함"
    title: str
    sender: str = ""
    receiver: str = ""
    doc_date: Optional[date] = None  # 메일 수신일 / 결재 상신일
    due_date: Optional[date] = None  # 추출된 마감일
    matched_text: str = ""  # 마감일이 언급된 원문 문장
    raw_snippet: str = ""  # 팝업에서 "원문 보기" 클릭 시 보여줄, 더 긴 본문 일부
    url: str = ""  # 상세 페이지로 돌아갈 수 있는 링크(있으면)
    bucket: str = field(default="", compare=False)  # classify 결과

    @property
    def id(self) -> str:
        raw = f"{self.source}|{self.folder}|{self.sender}|{self.title}|{self.due_date}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
