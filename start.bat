@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start_bosshunter.ps1"
if errorlevel 1 (
    echo.
    echo BossHunter 启动失败，请查看上面的错误信息。
    pause
)
endlocal
