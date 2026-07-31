"""Claude API로 기안 문서(+첨부파일)를 검토해서 오탈자/숫자오류/논증오류/누락을 찾아낸다.

문서 본문과 첨부파일 내용이 Anthropic 서버로 전송된다 (회사 데이터 정책을 먼저 확인하세요).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List

from .models import Attachment, DraftDocument, DraftReview, Finding

log = logging.getLogger("review.llm")

_MAX_BODY_CHARS = 12000
_MAX_ATTACHMENT_CHARS = 6000
_MAX_IMAGES_PER_ATTACHMENT = 8

SYSTEM_PROMPT = """당신은 대기업 결재라인의 매우 꼼꼼한 결재 전 검토자입니다.
상신 예정인 기안 문서(및 첨부파일 내용)를 검토해서, 결재권자가 서명하기 전에
반드시 확인해야 할 문제를 찾아내는 것이 임무입니다.

다음 항목을 중점적으로 확인하세요:
1. 오탈자: 명백한 오타, 띄어쓰기 오류, 문장이 어색하거나 비문인 부분
2. 숫자오류: 본문에 언급된 날짜/금액/비율/기간 등이 내부적으로 모순되지 않는지 확인
   (예: "1년" 이라고 했는데 시작일~종료일 계산이 1년이 아님, 금리가 본문과 표에서 다르게 적힘,
   합계 금액이 맞지 않음, 기표예정일이 이미 지난 날짜임 등)
3. 논증오류: 제시된 근거(사유)와 요청하는 내용이 논리적으로 맞지 않는 경우
   (예: 사유는 "금리 인하"인데 실제 표에는 금리가 오히려 오름, 연장을 요청하면서 기간이
   연장이 아니라 단축됨, 결론이 앞의 전제와 어긋남)
4. 누락: 이 문서 종류(기안지/법인인감신청서/사용인감신청서 등)에 통상 있어야 할 필수 항목이 빠진 경우
5. 첨부파일과 본문 간 불일치: 첨부파일에서 읽은 내용과 기안 본문에 적힌 내용이 서로 다른 경우

확실하지 않은 추측은 하지 마세요. 실제로 텍스트/이미지에 존재하는 근거에 기반해서만 지적하세요.
문제가 없으면 findings를 빈 배열로 반환하고 risk_level을 "정상"으로 하세요.
모든 설명은 한국어로, 결재권자가 바로 이해할 수 있도록 간결하게 작성하세요."""

RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_assessment": {
            "type": "string",
            "description": "이 문서에 대한 한두 문장짜리 총평",
        },
        "risk_level": {
            "type": "string",
            "enum": ["위험", "주의", "참고", "정상"],
            "description": "가장 심각한 지적사항 기준 전체 위험도",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["오탈자", "숫자오류", "논증오류", "누락", "형식오류", "기타"],
                    },
                    "severity": {"type": "string", "enum": ["위험", "주의", "참고"]},
                    "description": {"type": "string", "description": "무엇이 문제인지 구체적으로"},
                    "quote": {"type": "string", "description": "문제가 되는 원문 인용 (있으면)"},
                    "suggestion": {"type": "string", "description": "어떻게 수정해야 하는지"},
                },
                "required": ["category", "severity", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall_assessment", "risk_level", "findings"],
    "additionalProperties": False,
}


def _attachment_content_blocks(att: Attachment) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    if att.unsupported:
        blocks.append({"type": "text", "text": f"[첨부파일: {att.filename}] {att.note or '내용을 읽을 수 없습니다.'}"})
        return blocks

    if att.text.strip():
        text = att.text.strip()[:_MAX_ATTACHMENT_CHARS]
        note = f" ({att.note})" if att.note else ""
        blocks.append({"type": "text", "text": f"[첨부파일: {att.filename} 내용]{note}\n{text}"})

    if att.image_pngs:
        note = f" ({att.note})" if att.note else ""
        blocks.append({"type": "text", "text": f"[첨부파일: {att.filename} - 스캔본/이미지로 첨부됨]{note}"})
        for png_bytes in att.image_pngs[:_MAX_IMAGES_PER_ATTACHMENT]:
            b64 = base64.b64encode(png_bytes).decode("ascii")
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })

    if not blocks:
        blocks.append({"type": "text", "text": f"[첨부파일: {att.filename}] 내용을 추출하지 못했습니다."})

    return blocks


def _build_user_content(draft: DraftDocument) -> List[Dict[str, Any]]:
    header = (
        f"제목: {draft.title}\n"
        f"기안종류: {draft.form_type or '(알 수 없음)'}\n"
        f"기안자: {draft.drafter or '(알 수 없음)'}\n\n"
        f"[기안 본문]\n{draft.body_text.strip()[:_MAX_BODY_CHARS]}"
    )
    content: List[Dict[str, Any]] = [{"type": "text", "text": header}]
    for att in draft.attachments:
        content.extend(_attachment_content_blocks(att))
    content.append({"type": "text", "text": "위 문서를 검토하고 findings를 JSON으로 반환하세요."})
    return content


def review_draft(draft: DraftDocument, api_key: str, model: str, effort: str = "high") -> DraftReview:
    import anthropic

    if not api_key:
        return DraftReview(draft=draft, error="ANTHROPIC_API_KEY 가 설정되어 있지 않습니다.")

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_content(draft)}],
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Claude API 호출 실패: %s", draft.title)
        return DraftReview(draft=draft, error=f"API 호출 실패: {e}")

    if response.stop_reason == "refusal":
        return DraftReview(draft=draft, error="모델이 이 문서 검토를 거부했습니다 (정책상 사유).")

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        return DraftReview(draft=draft, error="모델 응답에서 텍스트를 찾지 못했습니다.")

    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as e:
        return DraftReview(draft=draft, error=f"모델 응답 JSON 파싱 실패: {e}")

    findings = [
        Finding(
            category=f.get("category", "기타"),
            severity=f.get("severity", "참고"),
            description=f.get("description", ""),
            quote=f.get("quote", ""),
            suggestion=f.get("suggestion", ""),
        )
        for f in data.get("findings", [])
    ]

    return DraftReview(
        draft=draft,
        overall_assessment=data.get("overall_assessment", ""),
        risk_level=data.get("risk_level", "정상"),
        findings=findings,
    )


def review_drafts(drafts: List[DraftDocument], api_key: str, model: str, effort: str = "high") -> List[DraftReview]:
    return [review_draft(d, api_key, model, effort) for d in drafts]
