@echo off
rem One-time PC setup (double-click). Creates ONE automatic job: "HookHouse Autopilot", which starts when you sign in
rem to Windows and runs everything: Telegram approvals, making videos, posting what you approve, the 09:00 campaign
rem list + report and the 03:30 disk cleanup.
rem Also set Windows to never sleep while plugged in (Settings > System > Power), and keep the charger connected.
rem Remove later with: schtasks /Delete /TN "HookHouse Autopilot" /F
schtasks /Delete /TN "ClipFactory Daily Campaigns" /F >nul 2>&1
schtasks /Delete /TN "ClipFactory Telegram Bot" /F >nul 2>&1
schtasks /Create /F /SC ONLOGON /TN "HookHouse Autopilot" /TR "cmd /c D:\clipping-system\scripts\telegram_bot.cmd"
echo.
echo Done. Sign out and in again (or restart), or start it now by double-clicking scripts\telegram_bot.cmd
pause
