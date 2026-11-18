@echo off
rem HookHouse PC helper: makes videos for the cloud while this PC is on. The cloud keeps running when the PC is off.
rem It also opens the HookHouse Chrome window if it is closed (campaign joins, pins and books need it).
rem To start it with Windows: press Win+R, type shell:startup, Enter, and put a shortcut to this file in that folder.
cd /d "%~dp0.."
call "%~dp0chrome.cmd"
:loop
python cli.py cloud helper
rem if it ever stops (crash, network), start it again after a minute
timeout /t 60 /nobreak >nul
goto loop
