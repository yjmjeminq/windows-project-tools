@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-YGO.ps1" %*
set "result=%errorlevel%"
pause
exit /b %result%
