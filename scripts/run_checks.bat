@echo off
rem Runs the automated tests and the code-style check.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m pytest
set TESTS_EXIT=%ERRORLEVEL%
.venv\Scripts\python.exe -m ruff check .
set LINT_EXIT=%ERRORLEVEL%
echo.
echo pytest exit code: %TESTS_EXIT%   ruff exit code: %LINT_EXIT%  ^(0 = success^)
