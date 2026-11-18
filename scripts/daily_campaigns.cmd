@echo off
rem Daily 09:00: find new campaigns we can fulfil (ClippingAlpha read tools), fetch views for posted videos,
rem send the campaign pick list to Telegram, then the morning report (status, channel numbers, dashboard file).
cd /d D:\clipping-system
set PYTHONIOENCODING=utf-8
python cli.py campaign discover --hours 30 >> data\campaigns\discover.log 2>&1
python cli.py stats fetch >> data\campaigns\discover.log 2>&1
python cli.py bot digest >> data\campaigns\discover.log 2>&1
python cli.py bot report >> data\campaigns\discover.log 2>&1
python cli.py dashboard --no-open >> data\campaigns\discover.log 2>&1
