@echo off
rem HookHouse PC stand-in (owner 18 Nov: "until the cloud comes back the PC will do its tasks").
rem Answers Telegram, runs the dashboard buttons, posts approved videos, makes up to 4 videos a day and keeps the
rem live dashboard fresh. When GitHub is back it hands everything to the cloud (exit code 3) and stops for good.
rem Started with Windows from the Startup folder (shortcut file pc_standin.cmd there).
cd /d "%~dp0.."
title HookHouse PC stand-in
if not exist data\logs mkdir data\logs
set PYTHONIOENCODING=utf-8
echo HookHouse PC stand-in is running. Log: data\logs\pc_standin.log  (close this window to stop it)
:loop
python cli.py pc run >> data\logs\pc_standin.log 2>&1
if errorlevel 3 goto done
rem a crash or network trouble: start again after a minute
timeout /t 60 /nobreak >nul
goto loop
:done
echo The cloud has taken over. This window can be closed.
