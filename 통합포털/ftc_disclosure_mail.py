# -*- coding: utf-8 -*-
"""공정위 "공시대상기업집단 대규모내부거래(상품ㆍ용역거래)" 취합요청 협조전 공용 모듈.

cashflow_plan_mail.py와 같은 구조입니다 — hub_db(참조자 목록ㆍ발송이력ㆍ서식 파일)만
써서 발송에 필요한 제목ㆍ본문ㆍ참조자ㆍ첨부파일을 준비하고, 실제 그룹웨어 협조전
임시저장은 groupware_rpa.create_groupware_draft가 담당합니다.

날짜(실적/예상치 구간) 계산 규칙 — 사용자가 준 예시 그대로:
  요청 시점이 속한 분기 안에서, 이번 달까지는 "실적", 남은 달은 "예상치".
  예) 5월에 발송 -> 4ㆍ5월 실적, 6월 예상치 (2분기)
      7월에 발송 -> 7월 실적, 8ㆍ9월 예상치 (3분기)
  분기의 마지막 달에 발송해서 그 분기 안에 남은 달이 없으면, 다음 분기 전체를
  예상치로 안내한다.
"""
from datetime import datetime

import hub_db


# (주)동양이 속한 유진 기업집단의 공시대상 계열회사 27개사 — 실제 협조전 원문의
# "다.대상 계열회사(27개 계열회사)" 목록을 그대로 옮겼다. 자주 바뀌는 자료가
# 아니라 하드코딩해두되, 갱신되면(기업집단현황공시 반영 등) 여기만 고치면 된다.
FTC_TARGET_AFFILIATES = [
    "유진기업(주)", "(주)유진에너팜", "남부산업(주)", "우진레미콘(주)", "이순산업(주)",
    "(주)지구레미콘", "현대개발(주)", "동화기업(주)", "유진레저(주)", "유진아이티서비스(주)",
    "유진엠(주)", "유진엠플러스(주)", "(주)유진로지스틱스", "(주)유진소닉", "(주)하루테크",
    "굿앤파트너스(주)", "현안기업(주)", "(주)유진디랩", "당진기업(주)", "성인산업(주)",
    "유진프라이빗에쿼티(주)", "(주)윌스프링인베스트먼트", "농업회사법인자연팜앤바이오(주)",
    "경산기업(주)", "유성산업(주)", "고운레저(주)", "유진이엔티(주)",
]


def _quarter_start_month(month: int) -> int:
    """월(1~12)이 속한 분기의 시작월(1, 4, 7, 10)을 반환한다."""
    return ((month - 1) // 3) * 3 + 1


def compute_ftc_period(today=None) -> dict:
    """요청 시점(오늘) 기준으로 분기ㆍ실적월ㆍ예상치월을 계산한다.

    반환: {year, quarter_num, quarter_start_month, quarter_end_month,
           actual_months: [int, ...], estimate_months: [int, ...],
           estimate_year, estimate_quarter_num,
           estimate_quarter_start_month, estimate_quarter_end_month}
    실적/예상치가 같은 분기 안에서 안 나뉘는 경우(분기 마지막 달에 발송)에는
    estimate_months가 빈 리스트이고, 대신 estimate_quarter_* 가 "다음 분기
    전체"를 가리킨다."""
    now = today or datetime.now()
    year = now.year
    month = now.month
    q_start = _quarter_start_month(month)
    quarter_num = (q_start - 1) // 3 + 1
    quarter_months = [q_start, q_start + 1, q_start + 2]

    actual_months = [m for m in quarter_months if m <= month]
    estimate_months = [m for m in quarter_months if m > month]

    if estimate_months:
        estimate_year = year
        estimate_quarter_num = quarter_num
        estimate_quarter_start_month = q_start
        estimate_quarter_end_month = q_start + 2
    else:
        # 분기 마지막 달에 발송 — 다음 분기 전체가 예상치 대상이다.
        next_q_start = q_start + 3
        if next_q_start > 12:
            estimate_year = year + 1
            next_q_start -= 12
        else:
            estimate_year = year
        estimate_quarter_num = (next_q_start - 1) // 3 + 1
        estimate_quarter_start_month = next_q_start
        estimate_quarter_end_month = next_q_start + 2

    return {
        "year": year,
        "quarter_num": quarter_num,
        "quarter_start_month": q_start,
        "quarter_end_month": q_start + 2,
        "actual_months": actual_months,
        "estimate_months": estimate_months,
        "estimate_year": estimate_year,
        "estimate_quarter_num": estimate_quarter_num,
        "estimate_quarter_start_month": estimate_quarter_start_month,
        "estimate_quarter_end_month": estimate_quarter_end_month,
    }


def _months_label(months: list) -> str:
    """[4, 5] -> '4,5월', [7] -> '7월'."""
    return ",".join(str(m) for m in months) + "월"


def build_title(period: dict) -> str:
    return (
        f"공시대상기업집단 대규모내부거래 상품용역거래 취합 요청 "
        f"({period['year'] % 100}년 {period['quarter_num']}분기)"
    )


def build_groupware_body_html(sender_name: str, period: dict, reply_deadline: str = None) -> str:
    """실제 협조전 원문 구조(거래상대방/거래기간/거래내용/자료작성기준/회신방법ㆍ회신기한/기타)를
    그대로 재현한다. reply_deadline을 지정하지 않으면 그 줄은 담당자가 그룹웨어에서
    직접 채우도록 비워둔다."""
    affiliates_text = ", ".join(FTC_TARGET_AFFILIATES)
    actual_label = _months_label(period["actual_months"]) if period["actual_months"] else ""

    if period["estimate_months"]:
        estimate_label = f"{_months_label(period['estimate_months'])} 예상치"
    else:
        estimate_label = (
            f"{period['estimate_quarter_num']}분기"
            f"({period['estimate_quarter_start_month']}~{period['estimate_quarter_end_month']}월) 예상치"
        )

    actual_clause = f"{actual_label} 실적 및 " if actual_label else ""
    deadline_html = f"<p><b>나. 회신기한 : {reply_deadline}</b></p>" if reply_deadline else ""

    return f"""
    <p>독점규제 및 공정거래에 관한 법률 제26조(대규모내부거래의 이사회 의결 및 공시)에 따라 아래와 같이 <b>상품ㆍ용역거래 내역</b>을 파악하고자 하오니 협조하여 주시기 바랍니다.</p>
    <p style="text-align:center;">- 아 래 -</p>
    <p><b>1. 거래상대방</b><br>
    가. 동일인(대주주) 또는 동일인 친족이 20%이상 출자한 계열회사<br>
    나. 상기조항의 계열회사의 자회사<br>
    다. 대상 계열회사({len(FTC_TARGET_AFFILIATES)}개 계열회사) : {affiliates_text}</p>
    <p><b>2. 거래기간 : {period['year']}년 {period['quarter_start_month']}월 ~ {period['year']}년 {period['quarter_end_month']}월</b></p>
    <p><b>3. 거래내용 : 상품 및 용역 거래 전체 ( 매출, 매입 )</b><br>
    ※ 분기별 상기 대상 계열회사와의 거래규모 100억 초과 시 해당 분기 마감 전 이사회 승인 및 공시 진행 필요</p>
    <p><b>4. 자료 작성기준 : 매월 발행되는 세금계산서의 공급가액 기준으로 월별로 매출 및 매입액 작성</b></p>
    <p><b>5. 회신방법 및 회신기한</b><br>
    가. 회신방법 : 각 본부별 자료를 취합하여 본부장 승인후 협조전으로 회신요망.</p>
    {deadline_html}
    <p><b>6. 기타</b><br>
    가. {actual_clause}{estimate_label}를 입력해 주시기 바랍니다.</p>
    <p style="margin-top:16px;color:#888;font-size:12px;">작성자: {sender_name} (자금팀) · 본 협조전 초안은 통합 자금포털에서 자동 작성되었습니다.</p>
    """


def _load_attachments():
    attachments = []
    missing = []
    for slot, label in hub_db.FTC_DISCLOSURE_TEMPLATE_SLOTS:
        file = hub_db.get_ftc_disclosure_template_file(slot)
        if file:
            attachments.append(file)
        else:
            missing.append(label)
    return attachments, missing


def prepare_groupware_draft(sender_name: str) -> dict:
    """groupware_rpa.create_groupware_draft가 그대로 쓸 수 있는 형태로 제목ㆍ
    본문ㆍ참조자 목록(라벨)ㆍ첨부파일을 모아서 반환한다."""
    recipients = hub_db.list_ftc_disclosure_mail_recipients()
    recipient_labels = [r[2] for r in recipients if (r[2] or '').strip()]
    if not recipient_labels:
        return {"ok": False, "reason": "참조자(부서/이름) 목록이 비어있습니다 — 관리자 화면에서 먼저 등록해주세요."}

    attachments, missing = _load_attachments()
    if not attachments:
        return {"ok": False, "reason": "등록된 첨부 서식이 하나도 없습니다 — 먼저 서식 파일을 업로드해주세요."}

    period = compute_ftc_period()
    subject = build_title(period)
    body_html = build_groupware_body_html(sender_name, period)
    return {
        "ok": True,
        "subject": subject,
        "body_html": body_html,
        "recipient_labels": recipient_labels,
        "attachments": attachments,
        "missing_templates": missing,
        "period_label": f"{period['year']}-Q{period['quarter_num']}",
    }
