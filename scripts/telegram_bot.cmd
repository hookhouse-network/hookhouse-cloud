@echo off
rem HookHouse bot + autopilot (started at Windows sign-in by the "HookHouse Autopilot" task).
rem Receives your taps, makes videos ahead, asks for approval, posts what you approve, runs the 09:00 report and
rem the 03:30 cleanup. Restarts itself if it ever stops. Log: data\telegram\bot.log (crashes: console.log).
cd /d D:\clipping-system
set PYTHONIOENCODING=utf-8
:loop
python cli.py bot run >> data\telegram\console.log 2>&1
if %errorlevel% equ 3 (
  echo HookHouse is already running on this PC. This window can be closed.
  timeout /t 10 >nul
  exit /b 0
)
timeout /t 30 /nobreak >nul
goto loop
