# IT팀에 요청할 것 — tongyang-gwcheck 프로토콜 화이트리스트 등록

## 배경
통합포털(`http://10.62.15.197:9000`)의 "공통 > 그룹웨어 체크리스트" 화면에서
버튼 클릭 한 번으로 이 PC의 그룹웨어 체크리스트 프로그램(`3_실행.bat`)이 바로
실행되도록 커스텀 URL 프로토콜(`tongyang-gwcheck://`)을 만들어뒀다(`6_포털연동_등록.bat`으로
각 PC에 등록). 그런데 회사 Edge 브라우저 정책의 `AutoLaunchProtocolsFromOrigins`
(외부 프로토콜 자동실행 허용목록)에 이 프로토콜이 없어서, 지금은 버튼을 눌러도
아무 반응이 없다(브라우저가 조용히 무시함). 이 정책에 항목을 추가해줘야 동작한다.

그 전까지는 `3_실행.bat`을 바탕화면 바로가기로 만들어 직접 더블클릭하는 방식으로 대체 중.

## IT팀에 전달할 요청 내용

**요청**: Edge 브라우저 정책 `AutoLaunchProtocolsFromOrigins`(외부 프로토콜 자동실행
허용목록)에 아래 항목 추가

**현재 값** (레지스트리 `HKLM\SOFTWARE\Policies\Microsoft\Edge`, 값 이름
`AutoLaunchProtocolsFromOrigins`):
```json
[{"allowed_origins":["*"],"protocol":"printmade25"},{"allowed_origins":["*"],"protocol":"ptmcap"}]
```

**추가해야 할 항목**:
```json
{"allowed_origins":["http://10.62.15.197:9000"],"protocol":"tongyang-gwcheck"}
```

**전체 반영 후 값** (기존 항목 유지 + 새 항목 추가):
```json
[{"allowed_origins":["*"],"protocol":"printmade25"},{"allowed_origins":["*"],"protocol":"ptmcap"},{"allowed_origins":["http://10.62.15.197:9000"],"protocol":"tongyang-gwcheck"}]
```

**용도 설명**: 사내 통합포털(`10.62.15.197:9000`)에서 직원 개인 PC에 설치된
그룹웨어 마감일 체크 프로그램을 실행시키기 위한 커스텀 프로토콜입니다.
`printmade25`/`ptmcap`과 같은 방식으로, 클릭 시 로컬 프로그램만 실행되고
외부로 데이터가 나가지 않습니다.

**참고 문서**: [Microsoft Edge 정책 — AutoLaunchProtocolsFromOrigins](https://learn.microsoft.com/deployedge/microsoft-edge-policies#autolaunchprotocolsfromorigins)

(GPO로 배포하는 방식이면 "그룹정책관리편집기 > 관리 템플릿 > Microsoft Edge"에서도
같은 항목을 찾을 수 있음)

## 승인 후 할 일
승인·반영되면 별도 코드 수정 없이 통합포털의 "🔔 체크리스트 실행 시도" 버튼이
바로 정상 동작한다(현재 `common_groupware_checklist.html`에 이미 구현되어 있고,
"참고" 접이식 박스 안에 숨겨둔 상태 — 승인되면 그 박스를 펼쳐서 기본 노출로
바꿔주면 됨).
