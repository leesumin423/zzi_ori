# -*- coding: utf-8 -*-
"""월간보고서 "자금수지" 3개월 자금계획 제출 요청 메일 발송 공용 모듈.

danpan_mail.py와 같은 구조입니다 — hub_db(수신자 목록ㆍ발송이력ㆍ서식 파일)ㆍmailerㆍ
hub_config만 써서 실제 발송을 담당하고, "언제 보낼지"(수동 버튼/매월 자동)는 호출하는
쪽(app.py 관리자 화면, 자동발송 루프)이 결정합니다.

단판공시와 다른 점: 보낼 "현황 데이터"가 없고(사이트 목록 같은 게 아니라 그냥 매달
똑같은 요청), 대신 3개 서식 파일(레미콘ㆍ건자재ㆍ동양공통 / 플랜트 / 건설)을 첨부로
보낸다는 점입니다. 서식 파일 자체(제목의 "YYYY년 MM월~MM월" 날짜 범위 등)는 담당자가
매달 직접 갱신해서 관리자 화면에서 재업로드해야 합니다 — 이 모듈은 그때그때 등록된
파일을 그대로 첨부할 뿐, 날짜 텍스트를 자동으로 고쳐주지 않습니다.
"""
from datetime import datetime

import hub_config
import hub_db
import mailer


def _plan_period_label():
    """이번 발송이 요청하는 3개월 구간 라벨(예: "2026년 08월 ~ 10월") — 발송월 기준
    당월부터 2개월 뒤까지. 서식 파일 안의 날짜 텍스트와 반드시 일치한다는 보장은
    없다(담당자가 서식을 안 갱신했을 수도 있음) — 그래서 메일 본문에는 이 라벨을
    참고용으로만 적고, 실제 기준은 첨부 서식이라고 명시한다."""
    now = datetime.now()
    start_m = now.month
    end_m = start_m + 2
    end_y = now.year + (1 if end_m > 12 else 0)
    end_m = end_m - 12 if end_m > 12 else end_m
    if end_y == now.year:
        return f"{now.year}년 {start_m:02d}월 ~ {end_m:02d}월"
    return f"{now.year}년 {start_m:02d}월 ~ {end_y}년 {end_m:02d}월"


def _load_attachments():
    """등록된 서식 3종을 (파일명, bytes) 리스트로 반환. 없는 슬롯은 건너뛰고
    missing 목록에 담아서 호출한 쪽이 경고할 수 있게 한다."""
    attachments = []
    missing = []
    for slot, label in hub_db.CASHFLOW_PLAN_TEMPLATE_SLOTS:
        file = hub_db.get_cashflow_plan_template_file(slot)
        if file:
            attachments.append(file)
        else:
            missing.append(label)
    return attachments, missing


def build_mail_text(sender_name):
    period = _plan_period_label()
    return (
        f"안녕하세요, 자금팀 {sender_name}입니다.\n\n"
        f"{period}(3개월) 자금계획 제출 요청드립니다.\n"
        "첨부된 서식(레미콘ㆍ건자재ㆍ동양공통 / 플랜트 / 건설 중 해당 부서 서식)에 맞춰 "
        "작성하신 뒤 회신 부탁드립니다.\n\n"
        "문의사항은 자금팀으로 연락 주시기 바랍니다. 감사합니다."
    )


def build_groupware_body_html(sender_name, part_owners=None, reply_deadline=None):
    """그룹웨어 협조전 본문(HTML) — 실제 담당자가 작성해온 협조전 원문 구조
    (요청자료/회신방법/회신기한/작성시 유의사항)를 그대로 재현한다. part_owners는
    "본부/부문 : 담당자" 줄 리스트, reply_deadline은 "MM월 DD일(요일)까지" 문자열 —
    둘 다 지정하지 않으면 그 줄은 생략하고 담당자가 그룹웨어에서 직접 채우면 된다."""
    period = _plan_period_label()
    owners_html = ""
    if part_owners:
        owners_html = "<p>" + "<br>".join(f"▶{line}" for line in part_owners) + "</p>"
    deadline_html = f"<p><b>3. 회신기한 : {reply_deadline}</b></p>" if reply_deadline else ""
    return f"""
    <p>원활한 자금관리를 위하여 아래와 같이 자금계획 작성을 요청하오니 해당 부서에서는 첨부파일 양식에 맞춰 작성 후 기한내 회신 바랍니다.</p>
    <p style="text-align:center;">- 아 래 -</p>
    <p><b>1. 요청자료</b><br>- {period} (3개월) 자금 계획</p>
    <p><b>2. 회신방법 : 팀장 전결로 자금팀 참조 협조전 발송</b></p>
    {owners_html}
    {deadline_html}
    <p><b>4. 작성시 유의 사항</b><br>
    - 부가세 포함 실제 지출금액으로 작성 (단위 : 백만원)<br>
    - 증빙(세금계산서 등) 발생일이 아닌 수금 및 지출 예정일 기재<br>
    - 현금 기준 작성 (어음 수금분은 만기일에 표기)<br>
    - 부정확한 자료 제출시 자금 지출 제한 및 추가 협조전 회신이 발생할 수도 있으며, 매월 계획대비 실적 보고 하오니 정확한 자금수지 계획 작성 요망</p>
    <p style="margin-top:16px;color:#888;font-size:12px;">작성자: {sender_name} (자금팀) · 본 협조전 초안은 통합 자금포털에서 자동 작성되었습니다.</p>
    """


def prepare_groupware_draft(sender_name):
    """그룹웨어 협조전 RPA(groupware_rpa.py)가 그대로 쓸 수 있는 형태로
    제목ㆍ본문ㆍ참조자 목록(라벨)ㆍ첨부파일을 모아서 반환한다. 이메일과 달리
    수신자의 '이메일 주소'는 필요 없고 라벨(부서/이름)만 있으면 된다 —
    그룹웨어 결재선 팝업에서 이름으로 검색해 참조자로 추가하기 때문."""
    recipients = hub_db.list_cashflow_plan_mail_recipients()
    recipient_labels = [r[2] for r in recipients if (r[2] or '').strip()]
    if not recipient_labels:
        return {"ok": False, "reason": "참조자(부서/이름) 목록이 비어있습니다 — 관리자 화면에서 먼저 등록해주세요."}

    attachments, missing = _load_attachments()
    if not attachments:
        return {"ok": False, "reason": "등록된 자금계획 서식이 하나도 없습니다 — 먼저 서식 파일을 업로드해주세요."}

    subject = f"{_plan_period_label()}(3개월) 자금수지 계획 요청의 건"
    body_html = build_groupware_body_html(sender_name)
    return {
        "ok": True,
        "subject": subject,
        "body_html": body_html,
        "recipient_labels": recipient_labels,
        "attachments": attachments,
        "missing_templates": missing,
    }


def build_mail_html(sender_name):
    period = _plan_period_label()
    return f"""
    <div style="font-family:'Malgun Gothic',sans-serif;font-size:14px;color:#222;line-height:1.7;">
      <p>안녕하세요, 자금팀 {sender_name}입니다.<br>
      <b>{period}(3개월) 자금계획</b> 제출 요청드립니다.</p>
      <p>첨부된 서식(레미콘ㆍ건자재ㆍ동양공통 / 플랜트 / 건설 중 해당 부서 서식)에 맞춰
      작성하신 뒤 회신 부탁드립니다.</p>
      <p>문의사항은 자금팀으로 연락 주시기 바랍니다. 감사합니다.</p>
      <p style="margin-top:16px;color:#888;font-size:12px;">
        본 메일은 통합 자금포털에서 발송되었습니다.
      </p>
    </div>"""


def send_monthly_mail(triggered_by='manual', sender_name='담당자', from_addr=None):
    """recipients가 비어있거나 서식이 하나도 없으면 발송하지 않고 실패로 반환합니다.
    반환값: {"ok": bool, "reason": str(실패시), "recipient_count", "attachment_count",
             "missing_templates": [...], "results"}"""
    recipients = hub_db.list_cashflow_plan_mail_recipients()
    to_emails = [r[1] for r in recipients if (r[1] or '').strip()]
    if not to_emails:
        return {"ok": False, "reason": "수신자(이메일)가 설정되어 있지 않습니다 — 관리자 화면에서 먼저 등록해주세요."}

    attachments, missing = _load_attachments()
    if not attachments:
        return {"ok": False, "reason": "등록된 자금계획 서식이 하나도 없습니다 — 먼저 서식 파일을 업로드해주세요."}

    year_month = datetime.now().strftime('%Y-%m')
    subject = f"[(주)동양 자금팀] {_plan_period_label()} 자금계획 제출 요청"
    body_text = build_mail_text(sender_name)
    body_html = build_mail_html(sender_name)

    result_send = mailer.send_mail_combined(
        to_emails, subject, body_text,
        from_addr=from_addr or hub_config.MAIL_FROM, body_html=body_html,
        attachments=attachments,
    )

    hub_db.log_cashflow_plan_mail(
        year_month=year_month, recipient_count=len(to_emails), triggered_by=triggered_by,
    )
    return {
        "ok": True,
        "recipient_count": len(to_emails),
        "attachment_count": len(attachments),
        "missing_templates": missing,
        "results": [result_send],
    }


def already_sent_this_month():
    return hub_db.was_cashflow_plan_mail_sent_for(datetime.now().strftime('%Y-%m'))
