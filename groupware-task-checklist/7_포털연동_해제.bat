@echo off
chcp 65001 >nul
set "PROTO=tongyang-gwcheck"

reg delete "HKCU\Software\Classes\%PROTO%" /f >nul 2>&1

echo 통합포털 연동을 해제했습니다.
pause
