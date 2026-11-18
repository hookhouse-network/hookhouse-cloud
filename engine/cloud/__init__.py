"""Running HookHouse in the cloud, with the PC as an optional helper (owner, 13 Nov 2026: "make sure all the things
are working automated and not need the PC to remain on... move to cloud and manage the code there, managed by my
phone"). Owner's choice: "Cloud now, PC as helper", ₹0, no card.

- GitHub (private repo, Actions free tier: 2,000 minutes a month): the code, the scheduled jobs (posting, stats,
  comments, reports, planning) and 1-2 priority renders a day. Video folders are kept as release assets of the
  private repo; the system's memory (databases, plans, logins) is one small encrypted bundle (state.py).
- Cloudflare Worker (free, no card): the Telegram bot's always-on front door. It answers status questions at once,
  records every tap and message, and wakes the GitHub jobs at the right times (cloud/worker/worker.js).
- The PC (when it is on): `python cli.py cloud helper` renders the remaining videos and hands them to the cloud.
- The phone: Telegram for daily control, the GitHub app to see runs, Claude Code on the web to change code.
"""
