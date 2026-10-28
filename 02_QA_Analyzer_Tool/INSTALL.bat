@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1

py -3 --version >nul 2>&1
if not errorlevel 1 (
  py -3 -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 exit /b 1
  exit /b 0
)

python --version >nul 2>&1
if not errorlevel 1 (
  python -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 exit /b 1
  exit /b 0
)

echo Python 3 was not found.
exit /b 1
