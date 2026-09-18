@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
"%~dp0.venv\Scripts\bosshunter.exe" web
endlocal
