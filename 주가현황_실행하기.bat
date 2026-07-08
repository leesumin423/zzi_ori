@echo off
cd /d "%~dp0"

echo =========================================
echo       주가현황 대시보드 실행기
echo =========================================
echo.

:: 1) Python 설치 확인 (python 또는 py 런처)
set PYCMD=
where python >nul 2>nul
if %errorlevel%==0 (
    set PYCMD=python
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set PYCMD=py
    )
)

if "%PYCMD%"=="" (
    echo [오류] 이 PC에 Python이 설치되어 있지 않습니다.
    echo.
    echo 아래 주소에서 Python을 먼저 설치해주세요:
    echo https://www.python.org/downloads/
    echo.
    echo 설치할 때 반드시 화면 하단의 "Add python.exe to PATH" 체크박스를 체크하세요!
    echo 설치가 끝나면 이 파일을 다시 더블클릭해주세요.
    echo.
    pause
    exit /b 1
)

echo 1) 필요한 프로그램(패키지) 설치 확인 중... (처음 실행 시 1~2분 정도 걸릴 수 있어요)
%PYCMD% -m pip install --disable-pip-version-check -q -r requirements.txt
if not %errorlevel%==0 (
    echo.
    echo [오류] 필요한 패키지 설치에 실패했습니다. 인터넷 연결을 확인해주세요.
    echo 계속 에러가 나면 이 창의 내용을 캡처해서 보내주세요.
    echo.
    pause
    exit /b 1
)

echo 2) 서버(server.py)를 별도 창에서 실행합니다...
start "주가현황 서버 (닫지 마세요)" cmd /k %PYCMD% server.py

echo 3) 잠시 후 브라우저에서 대시보드를 엽니다...
timeout /t 3 /nobreak > nul
start "" "http://localhost:5000/"

echo.
echo 실행이 완료되었습니다!
echo "주가현황 서버" 라는 이름의 검은 콘솔 창이 별도로 떠 있을 거예요.
echo 그 창을 닫으면 서버가 종료되니, 대시보드를 쓰는 동안은 그대로 켜두세요.
echo 만약 그 창에 빨간 에러 메시지가 보이면, 그 내용을 캡처해서 보내주세요.
echo.
pause
