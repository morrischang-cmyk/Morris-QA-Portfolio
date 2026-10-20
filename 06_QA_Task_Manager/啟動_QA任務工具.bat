@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 qa_mission_web.py
) else (
    python qa_mission_web.py
)

if errorlevel 1 pause
