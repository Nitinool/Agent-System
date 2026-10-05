@echo off
setlocal
cd /d "%~dp0"
set "ACTIVITY_PYTHON_ARGS="
set "ACTIVITY_GLOBAL_PYTHON=%ProgramFiles%\Python310\python.exe"
if not exist "%ACTIVITY_GLOBAL_PYTHON%" goto try_py
"%ACTIVITY_GLOBAL_PYTHON%" -c "import sys, tkinter, sqlite3; sys.exit(sys.version_info[:2] != (3, 10))" >nul 2>nul
if not errorlevel 1 (
    set "ACTIVITY_PYTHON=%ACTIVITY_GLOBAL_PYTHON%"
    goto run
)
:try_py
py -3.10 -c "import sys, tkinter, sqlite3; sys.exit(sys.version_info[:2] != (3, 10))" >nul 2>nul
if not errorlevel 1 (
    set "ACTIVITY_PYTHON=py"
    set "ACTIVITY_PYTHON_ARGS=-3.10"
    goto run
)
python -c "import sys, tkinter, sqlite3; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 (
    set "ACTIVITY_PYTHON=python"
    goto run
)
set "ACTIVITY_BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%ACTIVITY_BUNDLED_PYTHON%" goto missing_python
"%ACTIVITY_BUNDLED_PYTHON%" -c "import sys, tkinter, sqlite3; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 (
    set "ACTIVITY_PYTHON=%ACTIVITY_BUNDLED_PYTHON%"
    goto run
)
:missing_python
echo Python 3.10+ with Tkinter is required. Please install Python and try again.
if "%~1"=="--check-runtime" exit /b 1
pause
exit /b 1
:run
if "%~1"=="--check-runtime" (
    echo Python runtime OK: "%ACTIVITY_PYTHON%" %ACTIVITY_PYTHON_ARGS%
    exit /b 0
)
"%ACTIVITY_PYTHON%" %ACTIVITY_PYTHON_ARGS% "%~dp0activity_logger.py"
set "ACTIVITY_EXIT_CODE=%errorlevel%"
if not "%ACTIVITY_EXIT_CODE%"=="0" pause
exit /b %ACTIVITY_EXIT_CODE%
