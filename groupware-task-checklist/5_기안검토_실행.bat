@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo 먼저 "1_설치.bat" 과 "4_기안검토_설치.bat" 을 실행해주세요.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python review_drafts.py

if errorlevel 1 (
    echo.
    echo 오류가 발생했습니다. logs\review.log 파일을 확인해주세요.
    pause
)
