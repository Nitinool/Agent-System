@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\tools\run-existing.ps1" %*
if errorlevel 1 pause
