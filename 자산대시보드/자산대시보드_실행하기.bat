@echo off
cd /d "%~dp0"
echo =========================================
echo        내 자산 대시보드 실행기
echo =========================================
echo.
set PYCMD=
python --version >nul 2>nul
if %errorlevel%==0 set PYCMD=python
if "%PYCMD%"=="" (
    py --version >nul 2>nul
    if not errorlevel 1 set PYCMD=py
)
if "%PYCMD%"=="" (
    echo [안내] 이 PC에 Python이 설치되어 있지 않습니다.
    echo   1. https://www.python.org/downloads/ 에서 설치하세요.
    echo   2. 설치 첫 화면 아래 "Add python.exe to PATH" 를 꼭 체크하세요.
    echo   3. 설치가 끝나면 이 실행기를 다시 더블클릭하세요.
    echo.
    pause
    exit /b 1
)
if not exist "data" mkdir data
echo 1) 필요한 프로그램 확인 중... (처음 한 번은 1분 정도 걸려요)
%PYCMD% -m pip install --disable-pip-version-check -q openpyxl msoffcrypto-tool
if errorlevel 1 (
    echo [안내] 필요한 프로그램 설치에 실패했습니다. 인터넷 연결을 확인해주세요.
    pause
    exit /b 1
)
echo.
echo 2) data 폴더의 엑셀을 읽습니다.
%PYCMD% asset_dashboard.py
if errorlevel 1 (
    echo.
    echo 위 [안내] 메시지를 확인해주세요. 해결이 안 되면 이 창을 캡처해서 보내주세요.
    pause
    exit /b 1
)
exit /b 0
