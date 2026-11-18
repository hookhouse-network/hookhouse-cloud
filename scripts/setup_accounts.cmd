@echo off
rem HookHouse setup assistant (double-click). Opens a checklist + a browser window that walks you through every
rem account and key: it opens each page, gives Copy buttons, picks up keys by itself, checks and saves them,
rem connects the channels and ticks your to-do list. You sign in and press the buttons the sites keep for people.
rem Run it again any time: it remembers what is done.
cd /d D:\clipping-system
python -c "import playwright" >nul 2>&1
if errorlevel 1 (
  echo Installing Playwright once ^(free, about 40 MB^)...
  python -m pip install --quiet playwright
)
python -m engine.setup_assistant %*
if errorlevel 1 (
  echo.
  echo Something went wrong. Opening the checklist in your normal browser instead...
  python -m engine.setup_assistant --normal-browser
)
pause
