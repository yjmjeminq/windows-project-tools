@echo off
setlocal DisableDelayedExpansion
powershell.exe -WindowStyle Hidden -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Fixes\StartGame.ps1"
