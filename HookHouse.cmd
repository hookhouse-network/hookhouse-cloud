@echo off
rem HookHouse: one click starts the system (PC stand-in while GitHub is down) and opens the live dashboard.
cd /d "%~dp0"
python cli.py pc open
timeout /t 3 /nobreak >nul
