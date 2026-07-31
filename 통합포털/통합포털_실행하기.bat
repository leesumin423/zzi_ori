@chcp 65001 >nul
@echo off
cd /d "%~dp0"
echo =========================================
echo   통합 자금포털 (허브) 시작
echo =========================================
echo.
echo [주의] 이 창은 허브(로그인/탭 메뉴)만 켭니다.
echo        주가/공시, 자금(차입), 퇴직연금은 각자 따로 켜져 있어야
echo        탭을 눌렀을 때 화면이 보입니다 -- 한번에 다 켜려면
echo        "전체_실행하기.bat"을 대신 사용하세요.
echo.

set PYCMD=
where python >nul 2>nul
if %errorlevel%==0 (
    set PYCMD=python
) else (
    where py >nul 2>nul
    if %errorlevel%==0 ( set PYCMD=py )
)
if "%PYCMD%"=="" (
    echo [오류] 이 PC에 Python이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

%PYCMD% -m pip install --disable-pip-version-check -q -r requirements.txt

start "통합포털 허브" cmd /k "chcp 65001 >nul & %PYCMD% app.py"
timeout /t 2 /nobreak > nul
start "" "http://localhost:9000/"
exit /b 0
