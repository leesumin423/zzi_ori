@echo off
cd /d "%~dp0"
echo =========================================
echo        내 자산 대시보드 실행기
echo =========================================
echo.
set PYCMD=
where python >nul 2>nul
if %errorlevel%==0 (set PYCMD=python) else (
    where py >nul 2>nul
    if %errorlevel%==0 set PYCMD=py
)
if "%PYCMD%"=="" (
    echo [오류] Python이 설치되어 있지 않습니다. https://www.python.org/downloads/ 에서 설치해주세요.
    echo 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
    pause
    exit /b 1
)
if not exist "data" mkdir data
echo 1) 필요한 패키지 확인 중...
%PYCMD% -m pip install --disable-pip-version-check -q openpyxl msoffcrypto-tool
echo.
echo 2) data 폴더의 엑셀(급여 / 복지기금 대출 / 미국포트폴리오)을 읽습니다.
echo    미국포트폴리오 엑셀 비밀번호를 물어보면 입력하세요. (화면에 표시되지 않고, 어디에도 저장되지 않습니다)
echo.
%PYCMD% asset_dashboard.py
echo.
pause
