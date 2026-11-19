@echo off
rem HookHouse PC video maker (owner 19 Nov, option A): this PC makes videos while it is on and hands each one to the
rem cloud, which asks for approval and posts it on every platform of the right channel. Nothing else runs here.
rem Started hidden by scripts/start_pc_maker.ps1 (no window). Log: data\logs\pc_maker.log
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
set PYTHONIOENCODING=utf-8
:loop
python cli.py cloud helper --videos-only >> data\logs\pc_maker.log 2>&1
rem a crash or network trouble: start again after a minute
timeout /t 60 /nobreak >nul
goto loop
