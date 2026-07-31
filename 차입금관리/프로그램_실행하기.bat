@echo off
echo 패키지를 설치 중입니다...
pip install -r requirements.txt
echo.
echo 대시보드를 실행합니다...
streamlit run app.py
pause
