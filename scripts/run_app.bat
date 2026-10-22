@echo off
rem Starts the application in your browser.
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
  echo Run scripts\setup_windows.bat first.
  exit /b 1
)
.venv\Scripts\python.exe -m streamlit run app.py
