@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if errorlevel 1 (
  echo Could not open the application folder.
  goto failed
)

py -3 --version >nul 2>&1
if not errorlevel 1 (
  set "QA_PYTHON=py -3"
  goto python_ready
)

python --version >nul 2>&1
if not errorlevel 1 (
  set "QA_PYTHON=python"
  goto python_ready
)

echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
goto failed

:python_ready
%QA_PYTHON% -c "import pandas, openpyxl, PIL, playwright" >nul 2>&1
if errorlevel 1 (
  echo Installing required Python packages. This may take a few minutes.
  call "%~dp0INSTALL.bat"
  if errorlevel 1 goto failed
)

if not exist "%~dp0jira_config.local.json" (
  echo Missing jira_config.local.json in this folder.
  goto failed
)

echo Starting QA Analyzer...
%QA_PYTHON% "%~dp0qa_analyzer_web.py"
if errorlevel 1 goto failed
echo Server stopped.
pause
exit /b 0

:failed
echo.
echo Setup or startup failed. Please send a screenshot of this window to the maintainer.
pause
exit /b 1
