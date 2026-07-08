@echo off
REM Windows 작업 스케줄러에 등록해서 매일 아침 자동 실행하기 위한 스크립트.
REM 사용법:
REM   1. 아래 PROJECT_DIR 을 이 프로젝트를 실제로 복사한 경로로 수정하세요.
REM   2. 필요하면 PYTHON_EXE 도 본인 파이썬(또는 venv) 경로로 수정하세요.
REM   3. 작업 스케줄러 > 새 작업 만들기 > 트리거: 매일 원하는 시간
REM      동작: 프로그램/스크립트에 이 run_checklist.bat 의 전체 경로를 지정.

set PROJECT_DIR=C:\Users\%USERNAME%\groupware-task-checklist
set PYTHON_EXE=pythonw

cd /d "%PROJECT_DIR%"
"%PYTHON_EXE%" main.py
