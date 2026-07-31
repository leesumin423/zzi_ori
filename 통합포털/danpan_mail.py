# -*- coding: utf-8 -*-
"""단판공시(단일판매ㆍ공급계약체결) 월별 모니터링 메일 발송 공용 모듈.

hub_db(수신자 목록ㆍ발송이력)ㆍdanpan_tracking_db(현장별 담당부서 메모ㆍ월별 스냅샷)ㆍ
mailerㆍhub_config(발신자 계정)만 사용해 실제 발송을 담당합니다. "누구에게, 어떤 내용을"
결정하는 부분만 여기 있고, "언제 보낼지"(수동 버튼/매월 자동)와 "무엇을 보낼지(현장 목록
조회)"는 호출하는 쪽(통합포털 관리자 화면, 주가현황 서버)이 각자의 방식으로 준비해
sites만 넘겨줍니다 — 이 모듈 하나를 양쪽에서 그대로 import해 재사용하면 발송 로직이
두 곳에서 미묘하게 달라지는 걸 막을 수 있습니다.

메일은 "저희가 파악한 현황을 알려드립니다"가 아니라 "이번 달 변동내역을 회신해주세요"
요청 메일입니다 — 그래서 현장별 담당부서를 같이 보여줍니다(danpan_tracking_db.site_meta).
전월 스냅샷은 계속 저장해두되(향후 참고용), 화면에는 "전월 목록에서 빠진 현장"만
안내하고 개별 항목의 금액ㆍ기간 변동 여부는 표에 강조 표시하지 않습니다(사용자 요청).
"""
from datetime import datetime

import hub_config
import hub_db
import mailer
import danpan_tracking_db as tracking_db


def _fmt_amount(won):
    if not isinstance(won, (int, float)):
        return '-'
    return f"{won / 100_000_000:,.1f}억원"


def _fmt_period(site):
    if site.get('period_start') or site.get('period_end'):
        return f"{site.get('period_start') or '?'} ~ {site.get('period_end') or '?'}"
    return '미정'


def build_mail_html(sites, prev_snapshot, sender_name):
    site_meta = tracking_db.get_all_site_meta()
    month_label = datetime.now().strftime('%Y년 %m월')

    if not sites:
        table_html = '<p>이번 달 기준으로 진행 중인 관리 대상 현장이 없습니다.</p>'
    else:
        rows_html = []
        for i, s in enumerate(sites, 1):
            meta = site_meta.get(s.get('site_name'), {})
            dept = meta.get('department') or '-'
            rows_html.append(f"""
              <tr>
                <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{i}</td>
                <td style="padding:6px 8px;border:1px solid #ddd;">
                  <a href="{s.get('dart_url', '')}" style="color:#1a56db;text-decoration:none;">{s.get('site_name', '')}</a>
                </td>
                <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{dept}</td>
                <td style="padding:6px 8px;border:1px solid #ddd;">{s.get('counterparty', '')}</td>
                <td style="padding:6px 8px;border:1px solid #ddd;text-align:right;">{_fmt_amount(s.get('amount'))}</td>
                <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{s.get('initial_contract_date', '')}</td>
                <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{_fmt_period(s)}</td>
                <td style="padding:6px 8px;border:1px solid #ddd;text-align:center;">{s.get('latest_disclosure_date', '')} ({s.get('revision_count') or 0}차)</td>
              </tr>""")

        removed_names = set(prev_snapshot.keys()) - {s.get('site_name') for s in sites}
        removed_html = ''
        if removed_names:
            items = ''.join(f"<li>{name}</li>" for name in sorted(removed_names))
            removed_html = f"""
            <p style="margin-top:16px;color:#c0392b;">
              ⚠️ 전월 목록에 있었으나 이번 달 목록에서 빠진 현장(준공 등으로 관리 종료 추정) — 사실과 다르면 회신 부탁드립니다:
            </p>
            <ul style="color:#c0392b;">{items}</ul>"""

        table_html = f"""
        <table style="border-collapse:collapse;font-size:13px;width:100%;">
          <thead>
            <tr style="background:#f2f4f7;">
              <th style="padding:6px 8px;border:1px solid #ddd;">순번</th>
              <th style="padding:6px 8px;border:1px solid #ddd;">현장명</th>
              <th style="padding:6px 8px;border:1px solid #ddd;">담당부서</th>
              <th style="padding:6px 8px;border:1px solid #ddd;">계약상대방</th>
              <th style="padding:6px 8px;border:1px solid #ddd;">계약금액</th>
              <th style="padding:6px 8px;border:1px solid #ddd;">최초계약일</th>
              <th style="padding:6px 8px;border:1px solid #ddd;">공사기간</th>
              <th style="padding:6px 8px;border:1px solid #ddd;">최근공시(차수)</th>
            </tr>
          </thead>
          <tbody>{''.join(rows_html)}</tbody>
        </table>{removed_html}"""

    return f"""
    <div style="font-family:'Malgun Gothic',sans-serif;font-size:14px;color:#222;line-height:1.6;">
      <p>안녕하세요, 자금팀 {sender_name}입니다.<br>
      당월 단일판매ㆍ공급계약 변동내역 요청드립니다.</p>
      <p>아래는 현재 저희 쪽에서 파악하고 있는 {month_label} 기준 진행현황입니다. 담당부서에서
      확인하시고, 금액ㆍ공사기간 등 변경(예정) 사항이 있으면 회신 부탁드립니다.</p>
      {table_html}
      <p style="margin-top:16px;color:#888;font-size:12px;">
        본 메일은 통합 자금포털이 DART 공시 자료를 기준으로 자동 발송했습니다.
        자세한 내용은 통합 자금포털 &gt; 공시 &gt; 단판공시 화면에서도 확인하실 수 있습니다.
      </p>
    </div>"""


def build_mail_text(sites, sender_name):
    """HTML을 못 보는 메일클라이언트를 위한 텍스트 대체본(줄글 요약)."""
    month_label = datetime.now().strftime('%Y년 %m월')
    lines = [
        f"안녕하세요, 자금팀 {sender_name}입니다.",
        "당월 단일판매ㆍ공급계약 변동내역 요청드립니다.\n",
        f"[{month_label} 기준 진행현황]",
    ]
    if not sites:
        lines.append("이번 달 기준으로 진행 중인 관리 대상 현장이 없습니다.")
    else:
        site_meta = tracking_db.get_all_site_meta()
        for i, s in enumerate(sites, 1):
            dept = site_meta.get(s.get('site_name'), {}).get('department') or '-'
            lines.append(
                f"{i}. {s.get('site_name', '')} (담당: {dept}) / {s.get('counterparty', '')} / "
                f"{_fmt_amount(s.get('amount'))} / {_fmt_period(s)}"
            )
    lines.append("\n자세한 내용은 통합 자금포털 > 공시 > 단판공시 화면에서 확인해주세요.")
    return "\n".join(lines)


def _collect_cc_emails(sites):
    """고정 CC(자금팀 담당팀장 등) + 이번 달 발송 대상 현장들의 담당부서 상위자(CC)
    이메일을 모아 중복 없이 반환합니다."""
    site_meta = tracking_db.get_all_site_meta()
    cc = {row[1] for row in tracking_db.list_fixed_cc()}
    for s in sites or []:
        meta = site_meta.get(s.get('site_name'), {})
        cc_email = (meta.get('cc_email') or '').strip()
        if cc_email:
            cc.add(cc_email)
    return sorted(cc)


def send_monthly_mail(sites, triggered_by='manual'):
    """recipients가 비어있으면 발송하지 않고 실패로 반환합니다.
    반환값: {"ok": bool, "reason": str(실패시), "recipient_count", "cc_count", "site_count", "results"}"""
    recipients = hub_db.list_danpan_mail_recipients()
    if not recipients:
        return {"ok": False, "reason": "수신자가 설정되어 있지 않습니다 — 관리자 화면에서 먼저 등록해주세요."}

    year_month = datetime.now().strftime('%Y-%m')
    prev_snapshot = tracking_db.get_latest_snapshot_before(year_month)

    subject = f"[(주)동양 자금팀] {datetime.now().strftime('%Y년 %m월')} 단일판매ㆍ공급계약 변동내역 요청"
    body_text = build_mail_text(sites, hub_config.MAIL_FROM_DANPAN_NAME)
    body_html = build_mail_html(sites, prev_snapshot, hub_config.MAIL_FROM_DANPAN_NAME)
    to_emails = [r[1] for r in recipients]
    cc_emails = [e for e in _collect_cc_emails(sites) if e not in to_emails]
    result_send = mailer.send_mail_combined(
        to_emails, subject, body_text, cc_emails=cc_emails,
        from_addr=hub_config.MAIL_FROM_DANPAN, body_html=body_html,
    )

    tracking_db.save_snapshot(year_month, sites or [])
    hub_db.log_danpan_mail(
        year_month=year_month,
        recipient_count=len(recipients),
        site_count=len(sites) if sites is not None else None,
        triggered_by=triggered_by,
    )
    return {
        "ok": True,
        "recipient_count": len(recipients),
        "cc_count": len(cc_emails),
        "site_count": len(sites) if sites is not None else 0,
        "results": [result_send],
    }


def already_sent_this_month():
    return hub_db.was_danpan_mail_sent_for(datetime.now().strftime('%Y-%m'))
