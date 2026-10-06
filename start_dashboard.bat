@echo off
REM Starts the local dashboard and opens it in your browser.
cd /d "%~dp0"
REM Python environment lives outside OneDrive so it doesn't sync.
set VENV=%LOCALAPPDATA%\NotifierApp\venv
if not exist "%VENV%" (
  echo First run: setting up...
  py -3 -m venv "%VENV%" || goto :error
  "%VENV%\Scripts\python" -m pip install --quiet -r requirements.txt || goto :error
)
start "" http://127.0.0.1:8000
"%VENV%\Scripts\python" app.py
goto :eof
:error
echo Setup failed. Is Python 3.12 installed? https://www.python.org/downloads/
pause
