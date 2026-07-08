@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo 먼저 "1_설치.bat" 을 실행해주세요.
    pause
    exit /b 1
)

echo ============================================
echo  기안 결재 전 오류 검토 기능 추가 설치
echo ============================================
echo.
echo 이 기능은 기안 문서 내용을 Claude(Anthropic) API로 전송해서 검토합니다.
echo 회사 데이터 정책을 먼저 확인해주세요.
echo.

call ".venv\Scripts\activate.bat"
pip install -r requirements-review.txt

echo.
echo .env 파일에 다음 항목을 채워주세요 (메모장이 열립니다):
echo   - GW_APPROVAL_TEMP_URL   (전자결재 임시함 화면 URL)
echo   - ANTHROPIC_API_KEY      (https://console.anthropic.com 에서 발급)
echo   - DRAFT_FORM_FILTER      (선택, 검토할 양식명 - 비우면 전체)
timeout /t 2 >nul
notepad ".env"

echo.
echo 설치 완료! 이제 "5_기안검토_실행.bat" 을 실행하세요.
pause
