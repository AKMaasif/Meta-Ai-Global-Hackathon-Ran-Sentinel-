@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto :install
if exist ".venv" (
  echo The .venv folder exists but its Python is missing. Rename it and run this launcher again.
  goto :failed
)
where py >nul 2>nul
if errorlevel 1 goto :python
py -3 -m venv .venv
if errorlevel 1 goto :failed
goto :install
:python
where python >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.10 or newer from https://www.python.org/downloads/ and run this again.
  goto :failed
)
python -m venv .venv
if errorlevel 1 goto :failed
:install
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo This virtual environment needs Python 3.10 or newer. Rename .venv and run this again.
  goto :failed
)
echo Checking project dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
if not exist .env (
  copy .env.example .env >nul
  if errorlevel 1 goto :failed
  echo Created .env. Offline mode works without API keys. See README.md to enable Meta models.
)
".venv\Scripts\python.exe" run.py %*
if errorlevel 1 goto :failed
exit /b 0
:failed
echo.
echo Startup did not complete. Read the message above; no existing .env has been overwritten.
pause
exit /b 1
