@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" -Mode models
if errorlevel 1 (
 echo.
 echo Не удалось завершить запуск. См. сообщения выше.
 pause
 exit /b 1
)
