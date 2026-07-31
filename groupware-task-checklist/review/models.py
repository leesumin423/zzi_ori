from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# 위험도: 숫자가 작을수록 더 심각 (정렬용)
SEVERITY_ORDER = {"위험": 0, "주의": 1, "참고": 2, "정상": 3}


@dataclass
class Attachment:
    filename: str
    text: str = ""  # 추출된 텍스트 (비어있으면 텍스트 추출 실패/미지원)
    image_pngs: List[bytes] = field(default_factory=list)  # 스캔본 등 이미지로 대체 첨부할 페이지들
    unsupported: bool = False  # HWP 등 아예 처리 못하는 형식
    note: str = ""  # "3페이지 중 2페이지만 렌더링" 같은 참고 메모


@dataclass
class Finding:
    category: str  # 오탈자 | 숫자오류 | 논증오류 | 누락 | 형식오류 | 기타
    severity: str  # 위험 | 주의 | 참고
    description: str
    quote: str = ""
    suggestion: str = ""


@dataclass
class DraftDocument:
    title: str
    form_type: str = ""  # 기안지 / 법인인감신청서 / 사용인감신청서 등 (알 수 없으면 빈 문자열)
    drafter: str = ""
    body_text: str = ""
    url: str = ""
    attachment_paths: List[Path] = field(default_factory=list)  # drafts.py 가 다운로드한 원본 파일
    attachments: List[Attachment] = field(default_factory=list)  # 이후 attachments.py 로 추출된 내용

    @property
    def id(self) -> str:
        raw = f"{self.title}|{self.drafter}|{self.url}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class DraftReview:
    draft: DraftDocument
    overall_assessment: str = ""
    risk_level: str = "정상"  # 위험 | 주의 | 참고 | 정상
    findings: List[Finding] = field(default_factory=list)
    error: Optional[str] = None  # LLM 호출 자체가 실패한 경우 에러 메시지

    def sort_key(self):
        return (SEVERITY_ORDER.get(self.risk_level, 9), self.draft.title)
