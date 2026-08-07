# -*- coding: utf-8 -*-
"""정기공시 초안을 「정기공시_작성지침서.docx」(사용자가 실무 기준으로 직접 정리한
작성기준 요약본, 12개 장) 기준으로 실제 AI(Claude)가 읽고 검토하는 모듈.

기존 standards/rules.py는 "지침서 소제목이 초안 목차에 있는지"만 보는 구조적
체크(제목 키워드 매칭)라, 실제로 그 항목이 지침서가 요구하는 내용대로 "잘
작성됐는지"는 보지 못한다 — 이 모듈이 그 빈틈을 메운다. diff_engine(전기 대비
누락ㆍ변경, 단위)과 이 모듈(지침서 기준 내용 검토)은 서로 다른 질문에 답하므로
독립적으로 유지한다.

지침서 원문(.docx, 약 19,000자)은 전체를 그대로 프롬프트에 넣는다 — 12개 장을
쪼개서 넣으면 장 간 참조(예: "제3장 공통 + 제4장 개별")를 놓치기 쉽고, 문서
자체가 프롬프트 캐싱 최소 길이를 넘기면서도 한 번에 넣기에 충분히 작다.
"""
import os

import docx

from . import config

_ANTHROPIC_CLIENT = None
_GUIDE_TEXT_CACHE = None

MODEL = "claude-opus-5"

_SYSTEM_PROMPT_HEADER = """당신은 (주)동양의 정기공시(사업보고서ㆍ반기보고서ㆍ분기보고서) 작성 초안을
검수하는 공시 실무 전문가입니다. 아래는 회사가 실무 기준으로 직접 정리한 「정기공시
작성지침서」(금융감독원 「기업공시서식 작성기준」 발췌ㆍ요약, 12개 장) 원문입니다.
이 지침서를 근거로만 판단하세요 — 지침서에 없는 내용을 임의로 지적하지 마세요.

검토 원칙:
1. 지침서의 "필수 체크"ㆍ"❖ 원문 요지" 항목을 기준으로, 초안에 실제로 그 내용이
   반영됐는지 확인합니다. 목차 제목만 있고 지침서가 요구하는 세부 내용(예: 12개
   항목 중 일부, 8개 세부사항 등)이 빠져 있으면 지적하세요.
2. 지침서가 "해당없음"으로 명시한 장/절(예: 금융업 관련 조항, SPACㆍ외국기업
   전용 조문)은 검토 대상이 아닙니다 — 지적하지 마세요.
3. 확신이 없으면 지적하지 마세요. 초안에 실제로 문제가 있다고 지침서 근거를 들어
   설명할 수 있는 경우에만 findings에 포함하세요.
4. severity는 "critical"(지침서상 필수 기재사항이 명백히 누락됨), "warning"(기재는
   있으나 지침서 기준에 못 미치거나 애매함), "info"(참고할 만한 개선 제안) 중 하나로.
5. 각 finding에는 반드시 지침서의 어느 부분을 근거로 했는지(guide_basis)를
   구체적으로 인용하거나 요약해서 남기세요 — 근거 없는 지적은 하지 마세요.

--- 정기공시 작성지침서 원문 ---
"""

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_summary": {
            "type": "string",
            "description": "전체 검토 결과 1~2문장 요약",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chapter": {"type": "string", "description": "예: 제01장 회사의 개요"},
                    "location": {"type": "string", "description": "초안에서 해당 내용이 있는(또는 있어야 할) 섹션명"},
                    "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                    "issue": {"type": "string", "description": "구체적인 문제 설명"},
                    "guide_basis": {"type": "string", "description": "지침서의 어느 기준에 근거했는지"},
                    "suggestion": {"type": "string", "description": "어떻게 수정하면 되는지"},
                },
                "required": ["chapter", "location", "severity", "issue", "guide_basis", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall_summary", "findings"],
    "additionalProperties": False,
}


def _load_guide_text() -> str:
    global _GUIDE_TEXT_CACHE
    if _GUIDE_TEXT_CACHE is not None:
        return _GUIDE_TEXT_CACHE
    if not os.path.exists(config.GUIDE_DOCX_PATH):
        return ''
    d = docx.Document(config.GUIDE_DOCX_PATH)
    lines = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    _GUIDE_TEXT_CACHE = '\n'.join(lines)
    return _GUIDE_TEXT_CACHE


def _serialize_table(table) -> str:
    rows_text = []
    for row in table.rows:
        cells_text = [c.text for c in row.cells if c.text]
        if cells_text:
            rows_text.append(' | '.join(cells_text))
    if not rows_text:
        return ''
    return '[표]\n' + '\n'.join(rows_text)


def _serialize_draft_document(doc) -> str:
    """ParsedDocument를 지침서와 대조하기 좋은 평문으로 직렬화한다 — 섹션 제목을
    소제목처럼 남겨서 어느 장/항목에 해당하는지 모델이 알아보기 쉽게 한다."""
    parts = [f"문서명: {doc.doc_name}", f"회사명: {doc.company_name}", '']
    for section in doc.sections:
        if not section.title and not section.blocks:
            continue
        parts.append(f"## {section.title}")
        for block in section.blocks:
            if block.kind in ('paragraph', 'heading') and block.text:
                parts.append(block.text)
            elif block.kind == 'table' and block.table:
                table_text = _serialize_table(block.table)
                if table_text:
                    parts.append(table_text)
        parts.append('')
    return '\n'.join(parts)


def _get_client():
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is not None:
        return _ANTHROPIC_CLIENT
    if not config.ANTHROPIC_API_KEY:
        return None
    import anthropic
    _ANTHROPIC_CLIENT = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _ANTHROPIC_CLIENT


def is_available() -> bool:
    return bool(config.ANTHROPIC_API_KEY) and bool(_load_guide_text())


def review_document(doc) -> dict:
    """지침서 기준 AI 검수. 반환: {"available": bool, "overall_summary": str,
    "findings": list, "error": str|None}."""
    if not config.ANTHROPIC_API_KEY:
        return {
            "available": False,
            "overall_summary": '', "findings": [],
            "error": (
                "AI 검수를 사용하려면 Anthropic API 키가 필요합니다 — "
                "통합포털 폴더에 .anthropic_api_key 파일을 만들어 키를 넣거나, "
                "ANTHROPIC_API_KEY 환경변수를 설정해주세요. "
                "(키 발급: https://console.anthropic.com)"
            ),
        }

    guide_text = _load_guide_text()
    if not guide_text:
        return {
            "available": False,
            "overall_summary": '', "findings": [],
            "error": f"작성지침서 파일을 찾지 못했습니다: {config.GUIDE_DOCX_PATH}",
        }

    client = _get_client()
    draft_text = _serialize_draft_document(doc)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=[{
                "type": "text",
                "text": _SYSTEM_PROMPT_HEADER + guide_text,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }],
            output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
            messages=[{
                "role": "user",
                "content": (
                    "아래는 검토할 정기공시 초안입니다. 위 지침서 기준으로 검토해서 "
                    "findings를 작성해주세요.\n\n--- 초안 ---\n" + draft_text
                ),
            }],
        )
    except Exception as e:
        return {
            "available": True,
            "overall_summary": '', "findings": [],
            "error": f"AI 검수 중 오류가 발생했습니다: {e}",
        }

    if response.stop_reason == "refusal":
        return {
            "available": True,
            "overall_summary": '', "findings": [],
            "error": "AI가 이 요청을 처리하지 못했습니다(정책상 거부). 다시 시도해주세요.",
        }

    import json
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return {
            "available": True,
            "overall_summary": '', "findings": [],
            "error": "AI 응답에서 결과를 읽지 못했습니다.",
        }
    parsed = json.loads(text)
    return {
        "available": True,
        "overall_summary": parsed.get("overall_summary", ''),
        "findings": parsed.get("findings", []),
        "error": None,
    }
