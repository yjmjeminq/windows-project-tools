@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -NonInteractive -File "%~dp0Fixes\StartGame.ps1"
if errorlevel 1 pause
