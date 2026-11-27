@echo off
rem HookHouse Control Center v1 (P2b): read-only console at http://127.0.0.1:8765 (actions open the cloud dashboard)
cd /d "%~dp0.."
start "" http://127.0.0.1:8765
python -m engine.console.app
