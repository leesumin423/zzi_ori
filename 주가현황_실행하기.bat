@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo =========================================
echo       주가현황 대시보드 실행기
echo =========================================
echo.
echo 1) 서버(server.py)를 별도 창에서 실행합니다...
start "주가현황 서버 (닫지 마세요)" cmd /k python server.py

echo 2) 잠시 후 브라우저에서 대시보드를 엽니다...
timeout /t 3 /nobreak > nul
start "" "http://localhost:5000/"

echo.
echo 실행이 완료되었습니다!
echo "주가현황 서버" 라는 이름의 검은 콘솔 창이 별도로 떠 있을 거예요.
echo 그 창을 닫으면 서버가 종료되니, 대시보드를 쓰는 동안은 그대로 켜두세요.
echo 만약 그 창에 빨간 에러 메시지가 보이면, 그 내용을 캡처해서 보내주세요.
echo.
pause
