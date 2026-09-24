@echo off
title MediTrack Hospital Asset System
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  python -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Starting MediTrack...
echo Open http://127.0.0.1:5000 in your browser.
python app.py
pause
