@echo off
REM Saves your API keys into Windows Credential Manager (hidden typing).
cd /d "%~dp0"
REM Python environment lives outside OneDrive so it doesn't sync.
set VENV=%LOCALAPPDATA%\NotifierApp\venv
if not exist "%VENV%" (
  py -3 -m venv "%VENV%"
  "%VENV%\Scripts\python" -m pip install --quiet -r requirements.txt
)
"%VENV%\Scripts\python" -m notifier.set_keys
pause
