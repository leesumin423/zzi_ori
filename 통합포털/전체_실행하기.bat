@chcp 65001 >nul
@echo off
setlocal
set BASE=%~dp0
set STOCK_DIR=%BASE%..\주가현황
set TREASURY_DIR=%BASE%..\차입금관리
set PENSION_DIR=%BASE%..\퇴직연금통합관리시스템\퇴직연금통합관리시스템

echo =========================================
echo   (주)동양 통합 자금포털 -- 전체 실행
echo   (주가/공시 + 자금(차입) + 퇴직연금 + 허브, 총 4개 창이 뜹니다)
echo =========================================
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

echo 1) 주가/공시 서버 시작 (포트 5000)...
cd /d "%STOCK_DIR%"
start "주가공시-5000" cmd /k "chcp 65001 >nul & %PYCMD% server.py"

echo 2) 자금(차입금관리) 서버 시작 (포트 8501)...
cd /d "%TREASURY_DIR%"
start "자금차입금관리-8501" cmd /k "chcp 65001 >nul & %PYCMD% -m streamlit run app.py"

echo 3) 퇴직연금 서버 시작 (포트 8000)...
if exist "%PENSION_DIR%" (
    cd /d "%PENSION_DIR%"
    start "퇴직연금-8000" cmd /k "chcp 65001 >nul & %PYCMD% run_dashboard.py"
) else (
    echo    [경고] 퇴직연금 폴더를 찾을 수 없어 건너뜁니다: %PENSION_DIR%
)

echo 4) 통합포털 허브 시작 (포트 9000)...
cd /d "%BASE%"
%PYCMD% -m pip install --disable-pip-version-check -q -r requirements.txt
start "통합포털허브-9000" cmd /k "chcp 65001 >nul & %PYCMD% app.py"

echo.
echo 각 서버가 켜지는 중입니다(처음엔 패키지 설치로 몇 초~1분 정도 걸릴 수 있어요).
echo 창이 여러 개 뜬 게 정상입니다 -- 하나라도 닫으면 그 서비스만 안 보이게 됩니다.
echo 15초 후 통합포털을 자동으로 엽니다...
timeout /t 15 /nobreak > nul
start "" "http://localhost:9000/"

echo.
echo 이 창을 닫아도 위에 뜬 서버 창들은 계속 실행됩니다.
echo 종료하려면 뜬 서버 창들을 모두 닫아주세요.
exit /b 0
