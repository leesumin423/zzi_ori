@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo 먼저 "1_설치.bat" 을 실행해주세요.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python login_setup.py
pause
