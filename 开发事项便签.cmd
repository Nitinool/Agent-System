@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0todo-desktop\tools\start.ps1" -Develop
if errorlevel 1 pause
