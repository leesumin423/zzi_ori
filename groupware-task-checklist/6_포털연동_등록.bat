@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PROTO=tongyang-gwcheck"
set "TARGET=%~dp03_실행.bat"

echo ============================================
echo  통합포털 연동 등록
echo ============================================
echo.
echo 통합포털 화면에서 "체크리스트 실행" 버튼을 누르면
echo 이 PC에서 아래 프로그램이 자동으로 실행되도록 등록합니다:
echo   %TARGET%
echo.

if not exist ".venv" (
    echo [주의] 아직 "1_설치.bat"을 실행하지 않은 것 같습니다.
    echo        먼저 1_설치.bat, 2_로그인설정.bat을 실행해주세요.
    echo.
)

reg add "HKCU\Software\Classes\%PROTO%" /ve /d "URL:Dongyang Groupware Checklist Protocol" /f >nul
if errorlevel 1 goto :fail
reg add "HKCU\Software\Classes\%PROTO%" /v "URL Protocol" /t REG_SZ /d "" /f >nul
if errorlevel 1 goto :fail
reg add "HKCU\Software\Classes\%PROTO%\shell\open\command" /ve /d "\"%TARGET%\" \"%%1\"" /f >nul
if errorlevel 1 goto :fail

echo 등록 완료!
echo 이제 통합포털(공통 탭)에서 "체크리스트 실행" 버튼을 누르면
echo 이 PC에서 자동으로 실행됩니다.
echo.
echo (등록을 취소하고 싶으면 "7_포털연동_해제.bat"을 실행하세요.)
pause
exit /b 0

:fail
echo.
echo [오류] 레지스트리 등록에 실패했습니다 — 회사 보안정책(그룹정책)으로 막혀있을 수 있습니다.
echo        IT팀에 문의하거나, 평소처럼 "3_실행.bat"을 직접 더블클릭해서 사용해주세요.
pause
exit /b 1
