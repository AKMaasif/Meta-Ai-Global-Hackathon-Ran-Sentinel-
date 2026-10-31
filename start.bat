@echo off
rem One-click start for Windows: creates the virtual environment on first run, then starts RAN Sentinel.
cd /d "%~dp0"
if not exist .venv (
  echo Creating the Python environment, first run only...
  py -m venv .venv || goto :nopython
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt || goto :eof
) else (
  call .venv\Scripts\activate.bat
)
if not exist .env (
  copy .env.example .env >nul
  echo Created .env from .env.example. Add your Meta key after MODEL_API_KEY= to use the Meta models.
)
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:8000/ops/"
py run.py
goto :eof
:nopython
echo Python 3.10 or newer is needed: https://www.python.org/downloads/
pause
