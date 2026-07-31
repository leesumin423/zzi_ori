@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  최초 설치를 시작합니다. (몇 분 걸릴 수 있어요)
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않거나 PATH에 등록되어 있지 않습니다.
    echo python.org 에서 Python을 설치할 때 "Add Python to PATH"를 꼭 체크해주세요.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/4] 가상환경 만드는 중...
    python -m venv .venv
)

echo [2/4] 필요한 패키지 설치 중...
call ".venv\Scripts\activate.bat"
pip install -r requirements.txt

echo [3/4] 브라우저(Chromium) 설치 중...
playwright install chromium

if not exist ".env" (
    echo [4/4] 설정 파일(.env) 새로 만드는 중...
    copy ".env.example" ".env" >nul
    echo.
    echo .env 파일을 새로 만들었습니다.
    echo 잠시 후 메모장이 열리면 GW_LOGIN_URL 이 채워져 있는지만 확인하고 저장 후 닫아주세요.
    timeout /t 2 >nul
    notepad ".env"
) else (
    echo [4/4] .env 파일이 이미 있어서 건너뜁니다.
)

echo.
echo ============================================
echo  설치 완료! 이제 "2_로그인설정.bat" 을 더블클릭하세요.
echo ============================================
pause
