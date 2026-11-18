@echo off
rem HookHouse Chrome, hidden (no window): the signed-in browser the PC helper uses for campaign joins, pins and books.
rem The helper starts it by itself when needed; this file is only for starting it by hand.
set CH=C:\Program Files\Google\Chrome\Application\chrome.exe
if not exist "%CH%" set CH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
start "" "%CH%" --headless=new --remote-debugging-port=9333 --user-data-dir="%~dp0..\data\browser_profile" --no-first-run --window-size=1280,900 --user-agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36" about:blank
