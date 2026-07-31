@chcp 65001 >nul
@echo off
cd /d "%~dp0"
echo =========================================
echo   zzi_ori 최신 코드 배포 (GitHub -> 이 PC의 실제 서비스 폴더)
echo =========================================
echo.
echo 동료가 GitHub에 올린 변경사항을, 실제로 서비스 중인 폴더에 그대로
echo 옮겨줍니다. 이 창만 한 번 실행하면 됩니다 -- 안에서 알아서 다 처리합니다.
echo.
echo (주의) 이 PC에서 직접 코드를 고치는 중이었다면, 먼저 그 변경사항을
echo        커밋해두세요 -- 안 그러면 아래 1단계에서 막힙니다.
echo.
pause

echo.
echo [1/4] GitHub에서 최신 코드 받는 중(git pull)...
git pull origin main
if errorlevel 1 (
    echo.
    echo [오류] git pull이 실패했습니다 -- 위 메시지를 확인하세요.
    echo        보통 이 폴더에 커밋 안 된 변경사항이 남아있을 때 발생합니다.
    pause
    exit /b 1
)

echo.
echo [2/4] 주가현황/공시 -- 이 폴더 자체가 실제 서비스 폴더라 별도 복사가
echo        필요 없습니다. 아래 서버 재시작 안내만 참고하세요.

echo.
echo [3/4] 차입금관리 코드를 실제 서비스 폴더(..\차입금관리)로 동기화 중...
echo        (실데이터 DB/엑셀/설정 비밀번호 파일은 절대 건드리지 않습니다)
robocopy "차입금관리" "..\차입금관리" /E /XD data __pycache__ .claude 개발로그 ^
    /XF *.db *.xlsx *.log *secrets.toml credit_ratings.json historical_rates.json loan_details.json kpi_inputs.json
if %errorlevel% GEQ 8 (
    echo [오류] 차입금관리 동기화 중 문제가 발생했습니다.
) else (
    echo 차입금관리 동기화 완료.
)

echo.
echo [4/4] 통합포털 코드를 실제 서비스 폴더(..\통합포털)로 동기화 중...
echo        (관리자 비밀번호가 담긴 hub_config.py는 절대 덮어쓰지 않습니다)
robocopy "통합포털" "..\통합포털" /E /XD data __pycache__ ^
    /XF *.db *.log hub_config.py
if %errorlevel% GEQ 8 (
    echo [오류] 통합포털 동기화 중 문제가 발생했습니다.
) else (
    echo 통합포털 동기화 완료.
)

echo.
echo =========================================
echo   완료! 화면에 반영하려면 서버를 다시 켜야 합니다:
echo   - 주가현황(5000): 켜져 있는 cmd 창에서 Ctrl+C 후 python server.py 다시 실행
echo   - 통합포털(9000): 켜져 있는 cmd 창에서 Ctrl+C 후 python app.py 다시 실행
echo   - 차입금관리(8501): runOnSave가 켜져 있어 재시작 없이 자동 반영됩니다
echo   - 퇴직연금: 이 스크립트는 아직 퇴직연금은 다루지 않습니다(별도 저장소)
echo =========================================
pause
