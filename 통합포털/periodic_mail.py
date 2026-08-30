# -*- coding: utf-8 -*-
"""정기공시(사업ㆍ반기ㆍ분기보고서) 작성 요청 협조전 공용 모듈.

ftc_disclosure_mail.py/danpan_mail.py와 같은 구조 — hub_db(참조자 목록)만 써서
발송에 필요한 제목ㆍ본문ㆍ참조자를 준비하고, 실제 그룹웨어 협조전 임시저장은
groupware_rpa.create_groupware_draft가 담당한다.

작성내용표(장별 담당부서 매핑)는 사용자가 실제 쓰던 협조전 양식("제72기(2026년)
반기 보고서 작성 관련 자료 요청의 건")을 그대로 옮겼다. "작성기준 제N장 참조"는
「기업공시서식 작성기준(2026.6.30. 시행)」의 실제 장 번호와 대조 확인된 값이다.
"""
from datetime import date, timedelta, datetime

import hub_db

# (주)동양 기수 계산용 — 관측값 "2026년 = 제72기"를 기준으로 역산한 상수.
# (창립연도를 직접 아는 게 아니라 실제 공시 표지에서 확인한 값으로 역산한 것이라,
# 결산기가 바뀌거나 관측값이 틀어지면 이 상수만 조정하면 된다.)
_FISCAL_PERIOD_BASE_YEAR_OFFSET = 1954

# 순번, 내용(장 제목 + 세부 절), 담당부서, 비고(작성기준 참조).
# 반기ㆍ분기보고서는 "이사의 경영진단 및 분석의견"(4번 항목)에 일부 생략 규정이
# 있어 비고에 별도 표시했다.
PERIODIC_REPORT_ITEMS = [
    {
        "no": 1, "title": "제1장. 회사의 개요",
        "sub": ["1. 회사의 개요", "2. 회사의 연혁", "3. 자본금 변동사항", "4. 주식의 총수 등", "5. 정관에 관한 사항"],
        "dept": "회계팀, 자금팀, 법무팀", "note": "작성기준 제3장 참조",
    },
    {
        "no": 2, "title": "제2장. 사업의 내용",
        "sub": ["1. 사업의 개요", "2. 주요 제품 및 서비스", "3. 원재료 및 생산설비", "4. 매출 및 수주상황",
                "5. 위험관리 및 파생거래", "6. 주요계약 및 연구개발활동", "7. 기타 참고사항"],
        "dept": "기획팀, 회계팀, 건재부문 사업운영팀, 건설부문 사업관리팀, 유진한일합섬 재무팀",
        "note": "작성기준 제4장 참조",
    },
    {
        "no": 3, "title": "제3장. 재무에 관한 사항",
        "sub": ["1. 요약재무정보", "2. 연결재무제표", "3. 연결재무제표 주석", "4. 개별재무제표", "5. 개별재무제표 주석",
                "6. 배당에 관한 사항 등", "7. 증권의 발행을 통한 자금조달에 관한 사항",
                "8. 기타 재무에 관한 사항 (가.재무제표 재작성 등 유의사항 나.대손충당금 설정현황 다.재고자산 현황 등 라.수주계약현황)"],
        "dept": "회계팀, 자금팀", "note": "작성기준 제5장 참조",
    },
    {
        "no": 4, "title": "제4장. 이사의 경영진단 및 분석의견",
        "sub": [], "dept": "자금팀", "note": "작성기준 제6장 참조 (분기ㆍ반기보고서는 기재 제외 가능)",
    },
    {
        "no": 5, "title": "제5장. 회계감사인의 감사의견 등",
        "sub": ["1. 외부감사에 관한 사항", "2. 내부통제에 관한 사항"],
        "dept": "회계팀, 내부회계팀", "note": "작성기준 제5장 2절ㆍ3절 참조",
    },
    {
        "no": 6, "title": "제6장. 이사회 등 회사의 기관에 관한 사항",
        "sub": ["1. 이사회에 관한 사항", "2. 감사제도에 관한 사항", "3. 주주총회 등에 관한 사항"],
        "dept": "기획팀, 내부회계팀, 법무팀", "note": "작성기준 제7장 참조",
    },
    {
        "no": 7, "title": "제7장. 주주에 관한 사항",
        "sub": ["1. 최대주주 및 그 특수관계인의 주식소유 현황", "2. 주식소유 현황", "3. 주가 및 주식거래실적"],
        "dept": "자금팀", "note": "작성기준 제8장 참조",
    },
    {
        "no": 8, "title": "제8장. 임원 및 직원 등에 관한 사항",
        "sub": ["1. 임원 및 직원의 현황", "2. 임원의 보수 등"],
        "dept": "인사팀", "note": "작성기준 제9장 참조",
    },
    {
        "no": 9, "title": "제9장. 계열회사 등에 관한 사항",
        "sub": ["1. 계열회사의 현황(요약)", "2. 타법인 출자현황(요약)"],
        "dept": "유진기업 자금팀, 회계팀", "note": "작성기준 제7장 4절 참조",
    },
    {
        "no": 10, "title": "제10장. 대주주 등과의 거래내용",
        "sub": [], "dept": "회계팀", "note": "작성기준 제10장 참조",
    },
    {
        "no": 11, "title": "제11장. 그 밖에 투자자 보호를 위하여 필요한 사항",
        "sub": ["1. 공시사항 진행ㆍ변경사항", "2. 우발부채 등에 관한 사항", "3. 제재 등과 관련된 사항",
                "4. 작성기준일 이후 발생한 주요사항 등 기타사항"],
        "dept": "기획팀, 자금팀, 법무팀, 회계팀", "note": "작성기준 제11장 참조",
    },
    {
        "no": 12, "title": "제12장. 상세표",
        "sub": ["1. 연결대상 종속회사 현황", "2. 계열회사 현황", "3. 타법인 출자현황"],
        "dept": "회계팀, 유진기업 자금팀, 회계팀", "note": "작성기준 제11장의2 참조",
    },
]

_REPORT_TYPE_SHORT = {
    "사업보고서": "사업",
    "반기보고서": "반기",
    "분기보고서(1분기)": "1분기",
    "분기보고서(3분기)": "3분기",
}


def compute_periodic_period(today=None) -> dict:
    """오늘 날짜 기준으로 "지금 준비해야 할" 정기보고서(가장 최근에 끝난
    분기ㆍ반기ㆍ사업연도)를 판단한다.

    반환: {report_type, report_type_short, base_date(작성기준일), period_start,
           fiscal_year, fiscal_period_no(제N기), statutory_deadline, reply_deadline}
    """
    now = today or datetime.now()
    now_date = now.date() if hasattr(now, 'date') else now
    year = now_date.year

    candidates = [
        (date(year - 1, 12, 31), "사업보고서", 90),
        (date(year, 3, 31), "분기보고서(1분기)", 45),
        (date(year, 6, 30), "반기보고서", 45),
        (date(year, 9, 30), "분기보고서(3분기)", 45),
        (date(year, 12, 31), "사업보고서", 90),
    ]
    past = [c for c in candidates if c[0] <= now_date]
    base_date, report_type, deadline_days = past[-1] if past else candidates[0]

    period_start = date(base_date.year, 1, 1)
    statutory_deadline = base_date + timedelta(days=deadline_days)
    # 실제 사용하던 예시(작성기준일 6/30 -> 회신기한 8/3)가 법정기한(8/14)보다
    # 11일 앞선 것과 같은 간격으로 회신기한을 잡는다 — 부서 취합ㆍ검수 여유를 둠.
    reply_deadline = statutory_deadline - timedelta(days=11)

    fiscal_year = base_date.year
    fiscal_period_no = fiscal_year - _FISCAL_PERIOD_BASE_YEAR_OFFSET

    return {
        "report_type": report_type,
        "report_type_short": _REPORT_TYPE_SHORT[report_type],
        "base_date": base_date,
        "period_start": period_start,
        "fiscal_year": fiscal_year,
        "fiscal_period_no": fiscal_period_no,
        "statutory_deadline": statutory_deadline,
        "reply_deadline": reply_deadline,
    }


def _fmt(d: date) -> str:
    return f"{d.year}년 {d.month:02d}월 {d.day:02d}일"


def build_title(period: dict) -> str:
    return (
        f"제{period['fiscal_period_no']}기({period['fiscal_year']}년) "
        f"{period['report_type_short']} 보고서 작성 관련 자료 요청의 건"
    )


def build_groupware_body_html(sender_name: str, period: dict) -> str:
    rows_html = "".join(
        f"""
        <tr>
          <td style="text-align:center;">{item['no']}</td>
          <td>
            <b>{item['title']}</b>
            {"<br>" + "<br>".join(item['sub']) if item['sub'] else ""}
          </td>
          <td>{item['dept']}</td>
          <td>{item['note']}</td>
        </tr>"""
        for item in PERIODIC_REPORT_ITEMS
    )

    return f"""
    <p><b>자본시장과 금융투자업에 관한 법률 제159조 및 동법 시행령 제168조에 따라 {period['report_type']} 등의
    제출을 위한 자료 작성을 아래와 같이 요청드리오니 협조하여 주시기 바랍니다.</b></p>
    <p style="text-align:center;">- 아 래 -</p>
    <p><b>1. 작성기준 : {_fmt(period['base_date'])} 기준 ({_fmt(period['period_start'])} ~ {_fmt(period['base_date'])})</b></p>
    <p><b>2. 작성내용</b></p>
    <table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse; width:100%; font-size:13px;">
      <thead>
        <tr style="background:#f2f4f6;">
          <th style="width:6%;">순번</th><th style="width:44%;">내용</th>
          <th style="width:28%;">담당부서</th><th style="width:22%;">비고</th>
        </tr>
      </thead>
      <tbody>{rows_html}
      </tbody>
    </table>
    <p><b>3. 작성시 주의사항</b><br>
    가. 첨부한 「기업공시서식 작성기준」을 참조하시어 작성하여 주시기 바랍니다.<br>
    나. 작성 중 문의사항이 있으시면 문의하여 주시기 바랍니다.<br>
    다. 내부회계관리제도 감사 등에 따라 작성하신 자료는 반드시 협조전으로 회신해 주시기 바랍니다.</p>
    <p><b>4. 회신기한 : {_fmt(period['reply_deadline'])} ({['월','화','수','목','금','토','일'][period['reply_deadline'].weekday()]}요일)까지</b></p>
    <p>첨부 1. 기업공시서식 작성기준 1부.<br>
    &nbsp;&nbsp;&nbsp;&nbsp;2. 직전 {period['report_type']} 원문 1부. 끝.</p>
    <p style="margin-top:16px;color:#888;font-size:12px;">작성자: {sender_name} · 본 협조전 초안은 통합 자금포털에서 자동 작성되었습니다.</p>
    """


def prepare_groupware_draft(sender_name: str) -> dict:
    """groupware_rpa.create_groupware_draft가 그대로 쓸 수 있는 형태로 제목ㆍ
    본문ㆍ참조자 목록(라벨)을 모아서 반환한다. 첨부(작성기준 PDFㆍ직전 보고서
    원문)는 아직 자동 연결 전이라 본문에 "첨부 예정"으로만 안내하고, 실제
    파일은 그룹웨어에서 담당자가 직접 첨부해야 한다."""
    recipients = hub_db.list_periodic_mail_recipients()
    recipient_labels = [r[2] for r in recipients if (r[2] or '').strip()]
    if not recipient_labels:
        return {"ok": False, "reason": "참조자(부서/이름) 목록이 비어있습니다 — 관리자 화면에서 먼저 등록해주세요."}

    period = compute_periodic_period()
    subject = build_title(period)
    body_html = build_groupware_body_html(sender_name, period)
    return {
        "ok": True,
        "subject": subject,
        "body_html": body_html,
        "recipient_labels": recipient_labels,
        "attachments": [],  # 작성기준 PDFㆍ직전 원문은 그룹웨어에서 직접 첨부
        "period_label": f"{period['fiscal_year']}-{period['report_type_short']}",
        "period": period,
    }
