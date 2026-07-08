@echo off
REM Windows 작업 스케줄러 등록용 (조용히 백그라운드 실행, 콘솔창 없음).
REM 사람이 직접 실행할 때는 이 파일 대신 프로젝트 폴더의 3_실행.bat 을 쓰세요.
REM
REM 이 파일 자체는 경로를 수정할 필요가 없습니다 (자기 위치를 기준으로 동작).
REM 작업 스케줄러에는 이 run_checklist.bat 의 "전체 경로"만 등록하면 됩니다.

cd /d "%~dp0.."
".venv\Scripts\pythonw.exe" main.py
