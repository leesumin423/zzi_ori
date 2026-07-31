@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo   퇴직연금 통합 대시보드를 준비합니다...
echo   - index.html을 직접 더블클릭하면 데이터가 로드되지 않습니다.
echo   - 반드시 이 파일로 실행해주세요.
echo ========================================================
echo.

python run_dashboard.py

if errorlevel 1 (
    echo.
    echo 오류가 발생했습니다. 위 메시지를 확인해주세요.
    pause
)
