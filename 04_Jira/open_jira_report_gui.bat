@echo off
setlocal
title Jira Bug Report Tool

cd /d "%~dp0"
set "LOG=%~dp0launcher_error.log"

echo Jira Bug Report Tool
echo Current folder: %cd%
echo.

if not exist "jira_report_gui.py" (
  echo.
  echo ERROR: jira_report_gui.py was not found.
  echo Please unzip the whole package first, then run this bat file again.
  echo Current folder: %cd%
  pause
  exit /b 1
)

if not exist "jira_report.ps1" (
  echo.
  echo ERROR: jira_report.ps1 was not found.
  echo Please keep all files in the same folder.
  pause
  exit /b 1
)

echo Checking Python...
py -3 --version
if %errorlevel% equ 0 (
  echo.
  echo Starting GUI with py -3...
  echo If the GUI window is hidden, please check the taskbar.
  echo.
  py -3 "jira_report_gui.py" 1>"%LOG%" 2>&1
  if %errorlevel% equ 0 exit /b 0
)

echo.
echo py -3 failed. Trying python...
python --version
if %errorlevel% equ 0 (
  echo.
  echo Starting GUI with python...
  echo.
  python "jira_report_gui.py" 1>"%LOG%" 2>&1
  if %errorlevel% equ 0 exit /b 0
)

echo.
echo ERROR: Jira Bug Report Tool failed to start.
echo.
echo Please send this file to Morris:
echo %LOG%
echo.
type "%LOG%"
echo.
pause
exit /b 1
