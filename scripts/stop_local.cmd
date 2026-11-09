@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_local.ps1"
if errorlevel 1 (
    echo.
    echo 停止操作未完成，请根据上面的提示检查。
)
pause
