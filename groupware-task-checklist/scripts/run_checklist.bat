@echo off
REM Windows 작업 스케줄러에 등록해서 매일 아침 자동 실행하기 위한 스크립트.
REM 사용법:
REM   1. 아래 PROJECT_DIR 을 이 프로젝트를 실제로 복사한 경로로 수정하세요.
REM      (예: C:\Users\tyinc\-AI-\groupware-task-checklist)
REM   2. venv를 다른 이름/경로로 만들었다면 PYTHONW_EXE 경로도 맞춰 수정하세요.
REM   3. 작업 스케줄러 > 작업 만들기 > 트리거: 매일 원하는 시간
REM      동작: 프로그램/스크립트에 이 run_checklist.bat 의 전체 경로를 지정.
REM      (README의 "매일 자동 실행" 섹션에 스크린샷 없이도 따라할 수 있는 순서가 있습니다)

set PROJECT_DIR=C:\Users\%USERNAME%\-AI-\groupware-task-checklist
set PYTHONW_EXE=%PROJECT_DIR%\.venv\Scripts\pythonw.exe

cd /d "%PROJECT_DIR%"
"%PYTHONW_EXE%" main.py
