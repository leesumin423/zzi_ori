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

호출 방식: 별도 Anthropic API 키를 사고 싶지 않다는 결정에 따라, 기본은 이 PC에
설치된 **Claude Code CLI를 헤드리스(-p/--print)로 서브프로세스 호출**하는
방식이다 — 이미 쓰고 있는 Claude 구독 한도 안에서 동작하고, 그룹웨어 기안이
올라올 때마다 자동으로 도는 게 아니라 이 화면에서 사람이 체크박스를 누를 때만
1회 실행되므로 사용량이 예측 가능한 범위로 유지된다. CLI가 없거나 로그인이
안 되어 있으면, ANTHROPIC_API_KEY(.anthropic_api_key)가 설정된 경우에 한해
기존 Anthropic API 경로로 자동 대체한다(둘 다 없으면 안내 메시지만 표시).
"""
import json
import os
import shutil
import subprocess
import tempfile

import docx

from . import config

_ANTHROPIC_CLIENT = None
_GUIDE_TEXT_CACHE = None
_CLAUDE_CLI_PATH = ''  # '' = 아직 탐색 안 함, None으로 확정되면 '없음'을 의미

MODEL = "claude-opus-5"
# 이 기능의 목적은 "빨리 끝내기"가 아니라 "정확하게 검토되었는지"이므로, 시간
# 제한을 아예 두지 않는다(None = subprocess가 끝날 때까지 무기한 대기). 일찍
# 끊는 건 사용량을 아끼는 게 아니라 — 이미 처리한 작업을 통째로 버리고 재시도
# 시 누적 사용량만 더 쓰게 만든다(사용량은 대기 시간이 아니라 처리한 토큰
# 양으로 정해진다). 화면은 응답이 올 때까지 로딩 상태로 있다가, 끝나면 결과
# 페이지로 그대로 넘어가는 것 자체가 "완료 알림" 역할을 한다.
CLI_TIMEOUT_SEC = None
# 문서 내용만으로 판단하게 하고, 파일시스템ㆍ웹 등 실제 도구 사용은 전부 막는다
# (헤드리스 호출이라 권한 프롬프트가 뜨면 응답을 못 받고 멈출 수 있어서).
_CLI_DISALLOWED_TOOLS = 'Bash Read Write Edit Glob Grep WebFetch WebSearch NotebookEdit Agent Artifact'

_SYSTEM_PROMPT_HEADER = """당신은 (주)동양의 정기공시(사업보고서ㆍ반기보고서ㆍ분기보고서) 작성 초안을
검수하는 공시 실무 전문가입니다. 아래는 회사가 실무 기준으로 직접 정리한 「정기공시
작성지침서」(금융감독원 「기업공시서식 작성기준」 발췌ㆍ요약, 12개 장) 원문입니다.

검토는 두 갈래로 합니다 — A는 지침서를 근거로, B는 초안 문서 자체를 근거로 판단하세요.

[A. 지침서 충족 여부]
1. 지침서의 "필수 체크"ㆍ"❖ 원문 요지" 항목을 기준으로, 초안에 실제로 그 내용이
   반영됐는지 확인합니다. 목차 제목만 있고 지침서가 요구하는 세부 내용(예: 12개
   항목 중 일부, 8개 세부사항 등)이 빠져 있으면 지적하세요.
2. 지침서가 "해당없음"으로 명시한 장/절(예: 금융업 관련 조항, SPACㆍ외국기업
   전용 조문)은 검토 대상이 아닙니다 — 지적하지 마세요.
3. 지침서에 없는 내용을 임의로 지적하지 마세요.

[B. 초안 문서 자체의 자기모순ㆍ최신성]
4. 서술문(글로 쓴 설명)이 같은 문서 다른 항목의 수치ㆍ표와 모순되는지 봅니다. 예:
   "판매물량이 증가하였다"고 썼는데 다른 항목의 매출ㆍ생산실적 표는 전년 대비
   감소로 나오는 경우. 전년도(또는 직전 회차) 문구를 그대로 복사해서 이번 회차
   실적과 안 맞게 남아있는 경우도 포함합니다.
5. 거래처ㆍ계열회사ㆍ출자회사 등 상대방 회사명이 실제로는 상호가 바뀌었거나
   합병ㆍ흡수된 옛 이름 그대로 쓰여 있는 것으로 보이면(문맥상 널리 알려진 상호
   변경 등, 확신이 서는 경우에 한해) 지적하세요. 확신이 없으면 넘어가세요.
6. 단, "표 안에서 기초+증가-감소=기말" 같은 순수 산술 검증은 이미 별도 규칙
   엔진이 처리하고 있으니 여기서는 하지 마세요 — 산술 자체보다 "글로 쓴 설명이
   다른 데이터와 맞는 얘기인지" 같은, 읽고 이해해야 판단되는 문제에 집중하세요.

[공통 원칙]
7. 확신이 없으면 지적하지 마세요. 초안에 실제로 문제가 있다고 구체적 근거(지침서
   조항이든, 초안 안의 다른 부분 인용이든)를 들어 설명할 수 있는 경우에만
   findings에 포함하세요.
8. severity는 "critical"(필수 기재사항이 명백히 누락되었거나 명백한 오류/모순),
   "warning"(기재는 있으나 기준에 못 미치거나 애매함ㆍ확인 필요), "info"(참고할
   만한 개선 제안) 중 하나로.
9. 각 finding의 guide_basis에는 A유형이면 지침서의 어느 부분을 근거로 했는지,
   B유형이면 초안의 어느 부분과 모순되는지(해당 문구를 인용)를 구체적으로
   남기세요 — 근거 없는 지적은 하지 마세요.

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


def _find_claude_cli():
    """claude CLI 실행파일 경로. 프로세스가 뜬 뒤 PATH가 바뀌면 반영이 안 되니
    (Windows 환경변수는 새 프로세스에만 적용) 방금 설치했다면 통합포털을 재시작
    해야 잡힌다."""
    global _CLAUDE_CLI_PATH
    if _CLAUDE_CLI_PATH == '':
        _CLAUDE_CLI_PATH = shutil.which('claude')
    return _CLAUDE_CLI_PATH


def is_available() -> bool:
    if not _load_guide_text():
        return False
    return bool(_find_claude_cli()) or bool(config.ANTHROPIC_API_KEY)


def _run_via_cli(system_prompt: str, user_prompt: str, oauth_token: str = None):
    """반환: (parsed_dict, error_str) — 하나는 항상 None.

    system_prompt(지침서 원문 포함, 약 2만자)를 --system-prompt 인자로 넘기면
    Windows 명령줄 길이 제한(약 8191자)에 걸려 "인수가 너무 많습니다" 오류가
    난다(실측 확인함) — 그래서 system/user 프롬프트를 합쳐 표준입력(stdin)
    하나로만 넘긴다. stdin은 길이 제한이 사실상 없다.

    oauth_token: 이 사람 본인이 'claude setup-token'으로 발급받은 개인 토큰(선택) —
    있으면 서버 공용 로그인 대신 그 토큰(본인 구독 한도)으로 실행한다."""
    cli = _find_claude_cli()
    args = [
        cli, '-p', '--output-format', 'json',
        '--json-schema', json.dumps(_OUTPUT_SCHEMA, ensure_ascii=False),
        '--disallowedTools', _CLI_DISALLOWED_TOOLS,
    ]
    combined_prompt = system_prompt + '\n\n' + user_prompt
    env = dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN=oauth_token) if oauth_token else None
    # 헤드리스 호출이 실수로라도 이 프로젝트 파일을 건드리지 못하게 빈 임시
    # 폴더에서 실행한다 — 어차피 도구 사용은 위에서 다 막아뒀지만 이중 안전장치.
    with tempfile.TemporaryDirectory(prefix='periodic_ai_review_') as isolated_cwd:
        try:
            proc = subprocess.run(
                args, input=combined_prompt, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=CLI_TIMEOUT_SEC, cwd=isolated_cwd, env=env,
            )
        except subprocess.TimeoutExpired:
            return None, f'AI 검수가 {CLI_TIMEOUT_SEC}초 안에 끝나지 않아 중단했습니다. 문서가 크거나 응답이 지연되고 있습니다 — 잠시 후 다시 시도해주세요.'
        except FileNotFoundError:
            return None, 'Claude Code CLI를 실행하지 못했습니다 — 설치 상태를 다시 확인해주세요.'

    raw = (proc.stdout or '').strip()
    if not raw:
        detail = (proc.stderr or '').strip()
        return None, 'AI로부터 응답을 받지 못했습니다.' + (f' ({detail})' if detail else '')

    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        return None, 'AI 응답을 해석하지 못했습니다(예상한 JSON 형식이 아닙니다).'

    if outer.get('is_error'):
        msg = str(outer.get('result') or '알 수 없는 오류')
        if 'not logged in' in msg.lower() or '/login' in msg:
            if oauth_token:
                return None, (
                    '등록하신 개인 Claude 토큰이 유효하지 않거나 만료된 것 같습니다 — '
                    '내 정보 화면에서 claude setup-token 으로 새로 발급받아 다시 등록해주세요.'
                )
            return None, (
                'Claude Code CLI에 로그인되어 있지 않습니다 — 통합포털이 돌아가는 이 PC에서 '
                '터미널을 열고 claude login 을 한 번 실행해 로그인해주세요. (개인 Pro/Max 구독 계정으로 로그인)'
            )
        return None, f'AI 검수 중 오류: {msg}'

    result = outer.get('result')
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return None, 'AI가 구조화된 형식으로 답하지 않았습니다 — 다시 시도해주세요.'
    if not isinstance(result, dict):
        return None, 'AI 응답 형식을 이해하지 못했습니다.'
    return result, None


def _run_via_api(system_prompt: str, user_prompt: str):
    """반환: (parsed_dict, error_str) — 하나는 항상 None."""
    client = _get_client()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=[{
                "type": "text", "text": system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }],
            output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        return None, f'AI 검수 중 오류가 발생했습니다: {e}'

    if response.stop_reason == "refusal":
        return None, "AI가 이 요청을 처리하지 못했습니다(정책상 거부). 다시 시도해주세요."

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None, "AI 응답에서 결과를 읽지 못했습니다."
    return json.loads(text), None


def review_document(doc, oauth_token: str = None) -> dict:
    """지침서 기준 AI 검수. 반환: {"available": bool, "overall_summary": str,
    "findings": list, "error": str|None}.

    Claude Code CLI가 설치·로그인되어 있으면 그걸로(구독 한도 안에서 무료),
    없으면 ANTHROPIC_API_KEY가 있을 때만 Anthropic API로 대체한다.
    oauth_token: 요청한 사람 본인의 'claude setup-token' 토큰(선택) — 있으면
    서버 공용 로그인 대신 이 토큰(본인 구독 한도)으로 CLI를 실행한다."""
    guide_text = _load_guide_text()
    if not guide_text:
        return {
            "available": False,
            "overall_summary": '', "findings": [],
            "error": f"작성지침서 파일을 찾지 못했습니다: {config.GUIDE_DOCX_PATH}",
        }

    cli = _find_claude_cli()
    if not cli and not config.ANTHROPIC_API_KEY:
        return {
            "available": False,
            "overall_summary": '', "findings": [],
            "error": (
                "AI 검수를 쓰려면 이 PC에 Claude Code CLI가 설치·로그인되어 있어야 합니다 — "
                "터미널에서 claude login 을 한 번 실행해주세요. "
                "(방금 설치했다면 통합포털을 재시작해야 인식됩니다. "
                "또는 Anthropic API 키가 있다면 .anthropic_api_key 파일에 넣어도 됩니다.)"
            ),
        }

    system_prompt = _SYSTEM_PROMPT_HEADER + guide_text
    draft_text = _serialize_draft_document(doc)
    user_prompt = (
        "아래는 검토할 정기공시 초안입니다. 위 지침서 기준으로 검토해서 "
        "findings를 작성해주세요.\n\n--- 초안 ---\n" + draft_text
    )

    if cli:
        parsed, err = _run_via_cli(system_prompt, user_prompt, oauth_token=oauth_token)
    else:
        parsed, err = _run_via_api(system_prompt, user_prompt)

    if err:
        return {"available": True, "overall_summary": '', "findings": [], "error": err}

    return {
        "available": True,
        "overall_summary": parsed.get("overall_summary", ''),
        "findings": parsed.get("findings", []),
        "error": None,
    }
