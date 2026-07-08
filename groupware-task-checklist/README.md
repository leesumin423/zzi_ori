# 그룹웨어 업무 체크리스트 알리미

그룹웨어(메일함 + 전자결재)를 뒤져서, 본문에 마감일이 언급된 항목들을 찾아
**오늘/이번주/차주/기한지남** 으로 분류해 메모지 스타일 팝업으로 보여주는 도구입니다.

지난 메일에 적힌 마감일도(이미 지났더라도) "기한 지남" 항목으로 계속 챙겨주는 게 핵심입니다.

> ⚠️ 이 프로젝트는 사내망/그룹웨어에 접근 가능한 **로컬 PC에서 직접 실행**해야 합니다.
> (클라우드 실행 환경에서는 사내 그룹웨어로 나가는 네트워크 자체가 막혀 있어 동작하지 않습니다.)

## 동작 방식 요약

1. `login_setup.py` 를 한 번 실행해서 브라우저 창에 직접 로그인 → 로그인 세션(쿠키)을 `.state/storage_state.json` 에 저장
2. `main.py` 실행 시 저장된 세션을 재사용해서 로그인 (세션이 만료됐으면 `.env`에 ID/PW가 있는 경우 자동 로그인 시도)
3. 메일함 + 전자결재(부서함 완료함/참조·회람함, 개인함 완료함/참조·회람함) 목록을 열어
   각 항목의 제목/본문에서 "까지", "마감", "회신 바랍니다" 같은 표현 근처의 날짜와, 보낸사람/제목을 찾아냄
4. 오늘 날짜 기준으로 **기한지남 → 오늘 → 이번주 → 차주 → (그 이후는 월별로 묶어서, 예: "2026년 8월")** 순서로 분류
5. 메모지 스타일 팝업으로 표시. 각 항목에 보낸사람 / 마감일 / D-day / 원문 문구가 함께 표시됨.
   체크해서 "완료 표시 저장"하면 다음부터 안 보임

## 보안 주의사항

- **ID/PW는 절대 코드나 git에 커밋하지 마세요.** `.env` 파일에만 넣고, `.env`는 `.gitignore`에 이미 등록되어 있습니다.
- 기본 로그인 방식은 `.env`에 비밀번호를 저장하지 않아도 되는 **세션 재사용 방식**(`login_setup.py`)입니다.
  `.env`의 `GW_ID` / `GW_PW`는 세션이 끊겼을 때만 쓰이는 보조 수단이니, 굳이 채우지 않아도 됩니다.
- 채팅창 등에 비밀번호를 평문으로 입력하는 습관은 지양하시고, 필요하면 이후 비밀번호를 변경하시길 권장합니다.

## 설치

```bash
cd groupware-task-checklist
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
```

## 설정

1. `.env.example` 을 복사해 `.env` 로 저장하고 `GW_LOGIN_URL` 을 확인합니다.
2. 로그인 세션 만들기:
   ```bash
   python login_setup.py
   ```
   브라우저 창이 열리면 평소처럼 직접 로그인하세요(캡차/보안문자 등이 나와도 사람이 처리하면 됩니다).
   로그인 후, **메일함 / 전자결재 부서함 완료함 / 부서함 참조·회람함 / 개인함 완료함 / 개인함 참조·회람함**
   화면으로 각각 이동해서 주소창 URL을 복사해 `.env`의 해당 항목에 붙여넣으세요.
   - `GW_MAIL_LIST_URL`
   - `GW_APPROVAL_DEPT_COMPLETED_URL`
   - `GW_APPROVAL_DEPT_REFERENCE_URL`
   - `GW_APPROVAL_PERSONAL_COMPLETED_URL`
   - `GW_APPROVAL_PERSONAL_REFERENCE_URL`
3. 첫 실행은 눈으로 확인하며 하는 걸 권장합니다. `.env`에서 `HEADED=true` 로 바꾸고:
   ```bash
   python main.py
   ```
   브라우저가 뜨고 메일함/전자결재함을 순서대로 열어보는 걸 확인하세요.

## 목록 인식 방식과 한계 (중요)

이 저장소를 만들 때 실제 `gw.eugenes.co.kr` 화면 구조(HTML)를 확인할 수 없었기 때문에,
목록(메일 리스트, 결재함 리스트)을 인식하는 로직은 **범용 휴리스틱**으로 작성되어 있습니다
(`gw/scrape_common.py`): 페이지 안에서 "표처럼 반복되는 요소"를 자동으로 찾아 각 행을 클릭해봅니다.

실제로 돌려보면 다음과 같은 문제가 생길 수 있습니다.

- 목록이 아닌 엉뚱한 표(메뉴, 배너 등)를 "목록"으로 잘못 인식
- 페이지네이션(다음 페이지) 미지원 - 첫 화면에 보이는 항목만 조회 (기본 최대 60행)
- 목록이 iframe 안에 여러 겹으로 중첩된 경우 탐지가 어긋날 수 있음

**문제가 생기면:**
1. `.env`에서 `HEADED=true`, `SLOWMO_MS=300` 정도로 설정하고 `python main.py` 로 눈으로 확인
2. `logs/run.log` 에서 몇 건이 인식됐는지 확인
3. 필요하면 `gw/mail.py`, `gw/approval.py` 에서 `scan_rows(list_frame, ...)` 대신
   실제 화면에서 개발자도구(F12)로 확인한 정확한 CSS 선택자로 교체하는 게 가장 확실합니다.
   (예: `list_frame.query_selector_all("table.mailList tr")` 처럼)

## 날짜 인식 범위

`core/date_extract.py` 가 인식하는 표현들 (모두 "까지/마감/제출/회신/바랍니다" 등 마감 관련 키워드가
같은 문장에 있을 때만 마감일로 인정합니다):

- `7/3(금)`, `7.3`, `7-3`
- `7월 3일`
- `2026-07-03`, `2026.7.3`
- 오늘/금일, 내일/명일, 모레
- 이번주 금요일, 차주 월요일, 그냥 "금요일까지"
- 이번주까지, 차주까지, 월말까지
- "3일 이내", "1주일 이내", "D-3"

패턴이 더 필요하면 (예: "익일까지", "다음달 첫째주" 등) `core/date_extract.py`의
`_resolve_matches` 함수에 패턴을 추가하고 `tests/test_date_extract.py`에 테스트를 추가하세요.

## 완료 체크 저장

팝업에서 체크하고 "완료 표시 저장하고 닫기"를 누르면 `.state/task_state.json` 에 기록되어
다음 실행부터는 그 항목이 다시 뜨지 않습니다. (파일을 지우면 초기화됩니다.)

## 매일 자동 실행 (Windows 작업 스케줄러)

### 1) bat 파일 경로 수정

`scripts/run_checklist.bat` 을 메모장으로 열어 `PROJECT_DIR` 값을 실제 설치 경로로 맞춰주세요
(venv를 `.venv` 이름 그대로 만들었다면 나머지는 자동으로 맞습니다).

### 2) 작업 스케줄러 등록 - GUI 방식

1. 시작 메뉴에서 "작업 스케줄러" 실행
2. 오른쪽 "작업 만들기" 클릭
3. **일반** 탭: 이름 입력 (예: "그룹웨어 업무 체크리스트"), "가장 높은 수준의 권한으로 실행" 체크 불필요
4. **트리거** 탭 → 새로 만들기 → 매일, 원하는 시간(예: 오전 8시 30분) 지정
5. **동작** 탭 → 새로 만들기 → "프로그램/스크립트"에 `scripts\run_checklist.bat` 의 **전체 경로** 입력
   (예: `C:\Users\tyinc\-AI-\groupware-task-checklist\scripts\run_checklist.bat`)
6. 확인 → 완료

### 3) 작업 스케줄러 등록 - 명령어 방식 (더 빠름, 2번과 둘 중 하나만 하면 됨)

관리자 권한 없이 실행하는 cmd에서, 경로만 본인 것으로 바꿔서 실행하면 GUI 없이 바로 등록됩니다:

```powershell
schtasks /create /tn "그룹웨어 업무 체크리스트" /tr "C:\Users\tyinc\-AI-\groupware-task-checklist\scripts\run_checklist.bat" /sc daily /st 08:30
```

등록 확인: `schtasks /query /tn "그룹웨어 업무 체크리스트"`
삭제하고 싶을 때: `schtasks /delete /tn "그룹웨어 업무 체크리스트" /f`

### 4) 주의사항

- 그룹웨어 세션이 짧게 만료되는 경우, 자동 실행 시 로그인이 안 될 수 있습니다.
  이 경우 며칠에 한 번은 `python login_setup.py` 를 재실행해서 세션을 갱신해주거나,
  `.env`에 `GW_ID`/`GW_PW`를 채워 자동 로그인 폴백이 동작하게 하세요(선택 사항).
  로그인에 완전히 실패하면 화면에 오류 팝업이 뜨고 `logs/run.log`에 기록됩니다.
- PC가 꺼져있으면 당연히 실행되지 않습니다. 절전모드 진입 시각과 겹치지 않게 트리거 시간을 잡으세요.

## 테스트

날짜 추출/분류 로직은 실제 그룹웨어 접속 없이 테스트할 수 있습니다.

```bash
pip install -r requirements-dev.txt
pytest
```

## 프로젝트 구조

```
config.py              .env 설정 로딩
login_setup.py          최초 1회 수동 로그인 → 세션 저장
main.py                  전체 실행 오케스트레이션
gw/
  browser.py             Playwright 세션 wrapper (세션 재사용, iframe 탐색)
  auth.py                 로그인 확인 / 자동 로그인 폴백
  scrape_common.py        범용 목록 행 탐지/클릭 휴리스틱
  mail.py                  메일함 스캔
  approval.py               전자결재함 스캔
core/
  models.py                Task 데이터 모델
  date_extract.py           본문에서 마감일 추출 (사이트 무관, 순수 로직)
  text_parse.py              본문에서 보낸사람/제목 추출
  classify.py                기한지남/오늘/이번주/차주/월별 분류
  state.py                    완료 체크 영속화
ui/
  popup.py                    tkinter 메모지 팝업
scripts/
  run_checklist.bat            작업 스케줄러용 실행 스크립트
tests/                          date_extract / classify 단위 테스트
```
