# -*- coding: utf-8 -*-
"""통합포털 설정 파일 예시(템플릿). 실제 값은 여기 채우지 말고, 이 파일을
'hub_config.py'로 복사한 뒤 그 복사본에만 채워 넣으세요 — hub_config.py는
.gitignore에 등록돼 있어서 절대 GitHub에 올라가지 않습니다.

- SECRET_KEY: 로그인 세션 쿠키 서명용. 아무 긴 무작위 문자열로 바꾸세요.
- BOOTSTRAP_ADMIN_*: 프로그램을 처음 실행할 때 자동으로 만들어지는 관리자 계정입니다.
  (사용자 DB가 비어있을 때 딱 한 번만 생성되고, 그 다음부터는 이 값이 바뀌어도 반영되지 않습니다 —
   비밀번호를 바꾸고 싶으면 관리자 화면에서 계정을 삭제 후 재시작하거나, 나중에 비밀번호 변경
   기능이 추가되면 그걸 쓰세요.)
"""

import os

SECRET_KEY = "CHANGE_ME_TO_A_RANDOM_STRING"

# 차입금관리 폴더 경로 — 월간보고서 DB(monthly_report_db.py)와 시트 렌더링 공용 모듈
# (report_shared.py)을 그대로 재사용하기 위해 통합포털에서 import할 때 씁니다.
TREASURY_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "차입금관리")

BOOTSTRAP_ADMIN_USERNAME = "admin"
BOOTSTRAP_ADMIN_PASSWORD = "CHANGE_ME"

# 각 서비스가 실제로 떠 있는 포트 (각 프로그램의 실행 스크립트와 반드시 일치해야 합니다)
PORT_STOCK_DISCLOSURE = 5000   # 주가현황/공시 (Flask, 주가현황 폴더의 server.py)
PORT_TREASURY = 8501           # 자금(차입금관리) (Streamlit)
PORT_PENSION = 8000            # 퇴직연금 (정적 HTML, run_dashboard.py)
HUB_PORT = 9000                # 이 통합포털 자체의 포트

# 가입 시 아이디는 그룹웨어 계정(아이디)과 동일하게 받고, 초기 비밀번호/인증코드는
# "아이디@EMAIL_DOMAIN" 주소로 발송합니다. (예: shpark → shpark@example.com)
EMAIL_DOMAIN = "example.com"

# 메일 발송 설정 — 사내 메일 서버(전산팀에 문의) 정보로 채우세요. 비워두면
# mailer.py가 "테스트 모드"로 동작해 실제 메일을 보내지 않고 콘솔에만 출력합니다.
SMTP_HOST = ""              # 예: "spamout.example.com" 또는 내부 IP
SMTP_PORT = 25
SMTP_USER = ""              # 인증서 기반 릴레이라 비워도 되는 경우가 많음(내부망 SMTP는 보통 무인증)
SMTP_PASSWORD = ""
SMTP_USE_TLS = True
MAIL_FROM = "통합 자금포털 <noreply@example.com>"

# 단판공시(단일판매ㆍ공급계약체결) 월별 모니터링 메일 발신자 — 시스템 계정이 아니라
# 실제 담당자 이름/메일로 보내고 싶으면 채우세요.
MAIL_FROM_DANPAN = "담당자명(부서) <owner@example.com>"
MAIL_FROM_DANPAN_NAME = "담당자명"
