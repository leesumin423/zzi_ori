# -*- coding: utf-8 -*-
"""메일 발송 모듈.

hub_config.SMTP_HOST가 비어있으면 "테스트 모드"로 동작합니다: 실제 메일을 보내는 대신
콘솔에 로그를 남기고, 발송될 내용을 그대로 돌려줍니다(호출한 쪽에서 화면에 표시할 수 있도록).
나중에 hub_config에 실제 회사 SMTP 정보를 채우면 코드 변경 없이 바로 실제 발송으로 전환됩니다.
"""
import smtplib
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import hub_config


def is_test_mode():
    return not hub_config.SMTP_HOST


def send_mail(to_email, subject, body, from_addr=None, body_html=None):
    """메일을 보냅니다. 반환값: {"sent": bool, "test_mode": bool, "to": str, "subject": str, "body": str}

    테스트 모드에서는 실제로 발송하지 않고 sent=False, test_mode=True로 반환하며,
    호출한 쪽(app.py)이 이 내용을 화면에 그대로 보여줘서 개발/테스트를 계속할 수 있게 합니다.
    from_addr을 지정하면 hub_config.MAIL_FROM 대신 그 발신자로 보냅니다(예: 담당자 개인 메일).
    body_html을 지정하면 표처럼 서식이 필요한 메일을 HTML로 보내고, body는 HTML을 못 보는
    메일클라이언트를 위한 텍스트 대체본으로 함께 실립니다(멀티파트/alternative).
    """
    from_addr = from_addr or hub_config.MAIL_FROM
    result = {"sent": False, "test_mode": is_test_mode(), "to": to_email, "subject": subject, "body": body}

    if is_test_mode():
        print(f"[메일 발송 - 테스트 모드] from={from_addr} to={to_email} subject={subject}\n{body}\n")
        return result

    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", _charset="utf-8"))
        msg.attach(MIMEText(body_html, "html", _charset="utf-8"))
    else:
        msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email

    try:
        with smtplib.SMTP(hub_config.SMTP_HOST, hub_config.SMTP_PORT, timeout=10) as server:
            if hub_config.SMTP_USE_TLS:
                server.starttls()
            if hub_config.SMTP_USER:
                server.login(hub_config.SMTP_USER, hub_config.SMTP_PASSWORD)
            server.sendmail(from_addr, [to_email], msg.as_string())
        result["sent"] = True
    except Exception as e:
        print(f"[메일 발송 실패] to={to_email} error={e}")
        result["error"] = str(e)

    return result


def send_mail_bulk(to_emails, subject, body, from_addr=None, body_html=None):
    """여러 수신자에게 같은 내용을 한 명씩 개별 발송합니다(받는 사람이 서로의 주소를
    보지 못하도록 To를 한 명씩만 채움). 반환값: [send_mail(...) 결과, ...]"""
    return [send_mail(to_email, subject, body, from_addr=from_addr, body_html=body_html) for to_email in to_emails]


def send_mail_combined(to_emails, subject, body, cc_emails=None, from_addr=None, body_html=None, attachments=None):
    """받는사람 여러 명 + 참조(CC) 여러 명에게 메일 한 통을 보냅니다(To/Cc 헤더에 실제
    주소가 모두 보임 — 받는 사람들이 서로를 볼 수 있습니다). CC로 받은 사람이 "나는
    참고로만 받았다"는 걸 헤더로 구분할 수 있어야 하는 경우(예: 담당자의 상위자를
    참조로 넣을 때) 이 함수를 씁니다. send_mail_bulk(각자 따로, 서로 안 보임)와는
    용도가 다릅니다 — 섞어 쓰지 마세요.

    attachments를 주면(예: [("파일명.xlsx", bytes), ...]) 첨부파일이 붙습니다 —
    자금계획 서식처럼 매달 똑같은 양식 파일을 첨부해서 보내야 하는 경우용.

    반환값: {"sent": bool, "test_mode": bool, "to": [...], "cc": [...], "subject": str, "body": str}
    """
    from_addr = from_addr or hub_config.MAIL_FROM
    cc_emails = cc_emails or []
    attachments = attachments or []
    result = {
        "sent": False, "test_mode": is_test_mode(), "to": to_emails, "cc": cc_emails,
        "subject": subject, "body": body,
    }

    if is_test_mode():
        names = [a[0] for a in attachments]
        print(f"[메일 발송 - 테스트 모드] from={from_addr} to={to_emails} cc={cc_emails} subject={subject} 첨부={names}\n{body}\n")
        return result

    if not to_emails:
        result["error"] = "받는사람이 없습니다."
        return result

    if attachments:
        # 첨부파일이 있으면 mixed 컨테이너 안에 (본문 alternative 파트) + (첨부파일들)을 담는다.
        msg = MIMEMultipart("mixed")
        if body_html:
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(body, "plain", _charset="utf-8"))
            alt.attach(MIMEText(body_html, "html", _charset="utf-8"))
            msg.attach(alt)
        else:
            msg.attach(MIMEText(body, _charset="utf-8"))
        for filename, file_bytes in attachments:
            part = MIMEApplication(file_bytes)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
    elif body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", _charset="utf-8"))
        msg.attach(MIMEText(body_html, "html", _charset="utf-8"))
    else:
        msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_emails)
    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)

    try:
        with smtplib.SMTP(hub_config.SMTP_HOST, hub_config.SMTP_PORT, timeout=10) as server:
            if hub_config.SMTP_USE_TLS:
                server.starttls()
            if hub_config.SMTP_USER:
                server.login(hub_config.SMTP_USER, hub_config.SMTP_PASSWORD)
            server.sendmail(from_addr, list(to_emails) + list(cc_emails), msg.as_string())
        result["sent"] = True
    except Exception as e:
        print(f"[메일 발송 실패] to={to_emails} cc={cc_emails} error={e}")
        result["error"] = str(e)

    return result


def email_for_username(username):
    return f"{username}@{hub_config.EMAIL_DOMAIN}"
