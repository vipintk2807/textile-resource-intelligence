@echo off
rem One-time setup: creates a virtual environment and installs dependencies.
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" not found. Install Python 3.12 from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Could not create a Python 3.12 virtual environment. Check that Python 3.12 is installed: py -0p
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 (
  echo Installation failed. See README.md, Troubleshooting.
  exit /b 1
)
echo.
echo Setup complete. Start the app with: scripts\run_app.bat
