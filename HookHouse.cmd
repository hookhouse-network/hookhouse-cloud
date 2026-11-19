@echo off
rem HookHouse: one click starts the PC video maker (hidden) if it is not running, cleans the disk, opens the live dashboard.
cd /d "%~dp0"
python cli.py pc open
timeout /t 3 /nobreak >nul
