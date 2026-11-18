"""Command tool for the system. Run `python cli.py --help`.

Later the Telegram bot calls these same functions, so everything here also
works from your phone.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from engine import campaigns as camp
from engine import db
from engine.config import ROOT, channels, settings

sys.stdout.reconfigure(encoding="utf-8")


def cmd_channels(_args):
    for ch in channels():
        sched = ch.get("schedule", {})
        flag = "🇺🇸" if ch["market"] == "US" else "🇮🇳"
        print(f"#{ch['number']} {flag} {ch['name']:<24} {ch['type']:<9} "
              f"{sched.get('shorts_per_day', 0)} Short/day, {sched.get('long_per_week', 0)} long/week — {ch['niche']}")


def cmd_brain(args):
    from engine.brain import Brain
    brain = Brain()
    if args.action == "status":
        for name, state in brain.status().items():
            print(f"{name:<12} {state}")
        return
    result = brain.ask(args.task, args.prompt)
    print(f"[answered by {result.provider}]\n{result.text}")


def _print_campaign(c: dict):
    print(f"{c['id']}  —  {c['name']}")
    print(f"  India verdict: {c.get('india_verdict')} ({c.get('india_reason')})")
    print(f"  Score: {c.get('score')}/10   Status: {c.get('status')}")
    for r in c.get("score_reasons", []):
        print(f"    • {r}")
    print(f"  Pay: ${c.get('cpm_usd')}/1k views   Budget left: {c.get('budget_left_pct')}%   "
          f"Platforms: {', '.join(c.get('platforms') or ['?'])}")
    if c.get("required_tags"):
        print(f"  Required in caption: {', '.join(c['required_tags'])}")
    if c.get("allowed_sources"):
        print(f"  Allowed sources: {', '.join(c['allowed_sources'][:5])}")


def cmd_campaign(args):
    conn = db.connect()
    if args.action == "add":
        from engine.brain import Brain
        text = Path(args.file).read_text(encoding="utf-8")
        url = args.url or (re.search(r"https?://\S+", text) or [""])[0]
        c = camp.analyze(text, url, Brain())
        db.save_campaign(conn, c)
        proof = ROOT / "data" / "campaign_proof"
        proof.mkdir(parents=True, exist_ok=True)
        (proof / f"{c['id']}_{time.strftime('%Y%m%d')}.md").write_text(f"{url}\n\n{text}", encoding="utf-8")
        _print_campaign(c)
    elif args.action == "discover":
        from engine.discover import discover
        report = discover(hours=args.hours or 48, refresh=args.refresh)
        print(report)
    elif args.action == "list":
        items = db.list_campaigns(conn)
        if not items:
            print("No campaigns yet. Add one: python cli.py campaign add --file page.txt")
        for c in items:
            print(f"{c.get('score', 0):>4}/10  {c.get('india_verdict', '?'):<5} {c.get('status'):<18} "
                  f"{c['id']:<30} ${c.get('cpm_usd')}/1k  budget {c.get('budget_left_pct')}%")
    elif args.action in ("show", "budget", "join"):
        c = db.get_campaign(conn, args.id)
        if not c:
            sys.exit(f"No campaign '{args.id}'")
        if args.action == "budget":
            c["budget_left_pct"] = float(args.value)
            c = camp.evaluate(c)
        elif args.action == "join":
            c["joined_at"] = time.time()
        db.save_campaign(conn, c)
        _print_campaign(c)


def cmd_memory(args):
    from engine.memory import open_memory
    mem = open_memory()
    if args.action == "stats":
        print(f"Embedder: {mem.embedder.name}")
        print(mem.count() or "Memory is empty. Run: python cli.py memory seed")
    elif args.action == "add":
        item_id = mem.add(args.kind, args.text, channel=args.channel, performance=args.perf)
        print(f"Saved #{item_id}")
    elif args.action == "search":
        for h in mem.search(args.text, kind=args.kind, channel=args.channel, k=args.k):
            perf = f"{int(h.performance):,} views" if h.performance is not None else "no data"
            print(f"[{h.rank_score:.3f}] ({h.kind}, {perf}) {h.text}")
    elif args.action == "seed":
        n = seed_memory(mem)
        print(f"Added {n} playbook notes and channel profiles.")


def seed_memory(mem) -> int:
    """Load the clip playbook and channel profiles as starting knowledge."""
    n = 0
    playbook = (ROOT / "docs" / "03-clip-playbook.md").read_text(encoding="utf-8")
    for line in playbook.splitlines():
        line = line.strip()
        m = re.match(r"^(?:[-*]|\d+\.)\s+(.*)", line)
        if m and len(m.group(1)) > 15:
            mem.add("playbook", re.sub(r"\*\*", "", m.group(1)))
            n += 1
    for ch in channels():
        mem.add("note", f"{ch['name']}: {ch['niche']}. {ch['bio']}", channel=ch["id"],
                meta={"type": "channel_profile"})
        n += 1
    return n


def cmd_schedule(args):
    from engine.schedule import next_slots
    for t in next_slots(args.market.upper(), args.count):
        print(t.strftime("%a %d %b  %I:%M %p IST"))


def cmd_licenses(_args):
    from engine.licenses import check
    problems = check()
    print("✅ All tools and models allow commercial use." if not problems
          else "❌ Problems:\n" + "\n".join(f"  - {p}" for p in problems))


def _brain_and_memory():
    from engine.brain import Brain
    from engine.memory import open_memory
    return Brain(), open_memory()


def cmd_make(args):
    import json as _json
    from engine.config import channel as get_channel
    log = lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}")
    script = _json.loads(Path(args.script).read_text(encoding="utf-8")) if args.script else None
    brain, memory = (None, None) if script else _brain_and_memory()
    if args.kind == "story":
        from engine import story
        ch = get_channel(args.channel)
        out, meta = story.make(brain, ch, topic=args.topic, fmt="long" if args.long else "short",
                               script=script, memory=memory, log=log)
    elif args.kind == "brainsnack":
        if args.old:
            from engine import brainrot
            out, meta = brainrot.make(brain, get_channel("brain_snack"), topic=args.topic, script=script,
                                      memory=memory, log=log)
        else:
            from engine.snack import maker as snack
            if brain is None:
                brain, memory = _brain_and_memory()
            out, meta = snack.make(brain, get_channel("brain_snack"), topic=args.topic, fmt=args.format,
                                   memory=memory, log=log)
    elif args.kind == "kids":
        from engine import kids
        if brain is None:
            brain, memory = _brain_and_memory()
        out, meta = kids.make(brain, get_channel("bloop_and_friends"), topic=args.topic, memory=memory, log=log,
                              fmt="short" if args.short else "long")
    else:  # clips
        from engine import clips
        if not args.source:
            sys.exit("make clips needs --source <file or link>")
        campaign = db.get_campaign(db.connect(), args.campaign) if args.campaign else None
        brain, memory = _brain_and_memory()
        out, meta = clips.make_clips(brain, args.source, get_channel(args.channel or "hot_take_hq"), campaign=campaign,
                                     memory=memory, keep=args.keep, log=log)
    print(f"\n✅ Done: {out}")


def cmd_thumbs(args):
    import json as _json
    from engine.config import channel as get_channel
    from engine.story import make_thumbnails
    out = Path(args.folder)
    meta = _json.loads((out / "upload.json").read_text(encoding="utf-8"))
    script = _json.loads((out / "script.json").read_text(encoding="utf-8"))
    script["beats"] = meta.get("beats", script.get("beats", []))
    for p in make_thumbnails(get_channel(meta["channel"]), script, out):
        print(p)


def cmd_trends(args):
    """Today's trend ideas per channel (Wikipedia + Google Trends, never-topics removed)."""
    from engine import trends
    brain = None
    if not args.no_ai:
        from engine.brain import Brain                  # the memory database isn't needed here (slow to open)
        brain = Brain()
    hints = trends.trend_hints(brain, log=print)
    for ch, lines in hints.items():
        print(f"\n== {ch}")
        for ln in lines:
            print(f"  - {ln}")
    if not hints:
        print("No trend ideas today (feeds down or nothing fits).")


def cmd_review(args):
    import os
    from engine.review import build
    page = build()
    print(page)
    if not args.no_open:
        os.startfile(page)


def cmd_pitch(args):
    from engine import pitch as pk
    conn = pk.connect()
    if args.action == "import":
        print(f"{pk.import_from_campaigns(conn)} new prospects from creators who run clipping campaigns")
    elif args.action == "add":
        print("added", pk.add(conn, args.name, args.kind or "podcast", "owner", args.niche or "", args.url or "", args.notes or ""))
    elif args.action == "make":
        print(pk.make_pitch(conn, args.id))
    elif args.action == "status":
        pk.set_status(conn, args.id, args.value)
        print(f"{args.id}: {args.value}")
    elif args.action == "kit":
        print(pk.build_kit())
    else:
        for pid, name, st, src, nxt in conn.execute(
                "SELECT id, name, status, source, next_followup FROM prospects ORDER BY status, name"):
            due = time.strftime("%d %b", time.localtime(nxt)) if nxt else "-"
            print(f"{st:8} {pid:32} follow-up {due:7} {src}")


def cmd_dashboard(args):
    import os
    import time as _t
    from engine.dashboard import build
    page = build()
    print(page)
    if not args.no_open:
        os.startfile(page)
    while args.watch:                      # keep the page fresh (it reloads itself every 2 minutes)
        _t.sleep(120)
        build()


def cmd_week(args):
    from datetime import date as _date
    from engine import weekly
    log = lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}")
    start = args.start or None
    if args.action == "plan":
        brain, memory = _brain_and_memory()
        only = [s.strip() for s in args.channels.split(",")] if args.channels else None
        plan = weekly.plan_week(brain, _date.fromisoformat(start) if start else None, only=only, memory=memory, log=log)
        for it in plan["items"]:
            when = it["publish_at"][5:16].replace("T", " ")
            print(f"{when}  #{it['number']:<2} {it['channel_name']:<22} {it['kind']:<5} {it['status']:<9} {it.get('topic') or ''}")
        print(f"\nPlanned {len(plan['items'])} posts for the week of {plan['start']}. Next: python cli.py week make")
    elif args.action == "make":
        brain, memory = _brain_and_memory()
        only = [s.strip() for s in args.ids.split(",")] if args.ids else None
        plan = weekly.make_week(brain, start, only_ids=only, memory=memory, log=log)
        print(f"\n{weekly.summary(plan)}\nNext: python cli.py week review")
    elif args.action == "review":
        weekly.serve(start, lan=args.lan, port=args.port, open_browser=not args.no_open)
    else:  # status
        plan = weekly.load_plan(start or weekly.latest_week() or "")
        print(f"Week of {plan['start']}: {weekly.summary(plan)}")
        for it in plan["items"]:
            print(f"{it['publish_at'][5:16].replace('T', ' ')}  {it['status']:<12} {it['channel_name']:<22} "
                  f"{it['kind']:<5} {it.get('topic') or ''}{('  ⚠ ' + it['error']) if it.get('error') else ''}")


def cmd_payers(_args):
    from engine import campaign_safety as cs
    conn = cs.connect(db.connect())
    for pid, p in cs.payers().items():
        ok, why = cs.can_submit(conn, pid)
        print(f"{pid:<16} {cs.payer_tier(conn, pid):<9} {p['name']:<48} {why}")


def cmd_safety(args):
    from engine import campaign_safety as cs
    if args.action == "campaign":
        c = db.get_campaign(db.connect(), args.target)
        if not c:
            sys.exit(f"No campaign '{args.target}'")
        res = cs.check_campaign(c)
    else:  # offer
        text = Path(args.target).read_text(encoding="utf-8")
        res = cs.screen_offer(text, sender=args.sender or "", brand_domain=args.brand_domain or "",
                              attachments=args.attachment or [])
    icon = {"ALLOW": "✅", "OK": "✅", "REVIEW": "⚠️", "BLOCK": "⛔"}[res["verdict"]]
    print(f"{icon} {res['verdict']}")
    for r in res.get("block", []):
        print(f"  ⛔ {r}")
    for r in res.get("review", []) + res.get("flags", []):
        print(f"  ⚠️ {r}")
    if res.get("next_step"):
        print(f"  → {res['next_step']}")


def cmd_ledger(args):
    from engine import campaign_safety as cs
    conn = cs.connect(db.connect())
    if args.action == "add":
        lid = cs.ledger_add(conn, args.payer, args.stage, amount_usd=args.usd or 0.0, amount_inr=args.inr,
                            fx_mid=args.fx_mid, fx_effective=args.fx, fee_usd=args.fee, ref=args.ref or "",
                            purpose_code=args.purpose or "", fira_path=args.fira or "", notes=args.note or "",
                            foreign=not args.domestic)
        print(f"Saved ledger entry #{lid}")
    elif args.action == "tier":
        cs.set_tier(conn, args.payer, args.stage)
        print(f"{args.payer} is now {args.stage}")
    print(cs.report(conn))


def cmd_publish(args):
    from engine import publish
    acts = publish.plan_uploads(args.week, dry_run=not args.live)
    if not acts:
        print("Nothing approved to upload. Approve videos first: python cli.py week review")
    for a in acts:
        flag = "DRY RUN" if a.details.get("dry_run") else ("OK" if a.done else "NOT DONE")
        print(f"[{flag}] {a.platform:<9} {a.channel:<22} {a.when[:16]:<16} {a.what}  {a.result or ''}")
    if acts and not args.live:
        print("\nThis was a dry run: nothing was uploaded. Accounts get connected in Week 3.")


def cmd_connect(args):
    from engine import connect
    from engine.config import channel as get_channel
    if args.service == "gmail":                       # creator outreach: the HookHouse Gmail, send-only permission
        ok = connect.connect_gmail()
        print("✅ HookHouse Gmail connected (send only). Add POSTAL_ADDRESS to .env and pitches get a 📧 Send button."
              if ok else "❌ Not connected (no sign-in received)")
        return
    if not args.channel:
        sys.exit("connect youtube / meta needs --channel <number>")
    ch = get_channel(args.channel)["id"]
    if args.service == "youtube":
        ok = connect.connect_youtube(ch)
        print("✅ YouTube connected for " + ch if ok else "❌ Not connected (no sign-in received)")
        if ok:
            from engine import branding
            try:
                print("🎨 " + branding.apply(get_channel(ch)))
            except Exception as e:  # noqa: BLE001 - the 09:00 job tries again
                print(f"Channel page not written yet ({e}); the system tries again at 09:00.")
    else:
        login = "instagram" if args.instagram_login else "facebook"
        if not (args.ig_user_id and args.token and (args.page_id or login == "instagram")):
            sys.exit("connect meta needs --ig-user-id and --token, plus --page-id (or --instagram-login: no Page needed)")
        rec = connect.save_meta(ch, args.ig_user_id, args.page_id or "", args.token, args.page_token or "", login=login)
        import time as _t
        days = (f", valid {(rec['expires_at'] - _t.time()) / 86400:.0f} days" if rec["expires_at"] else
                " (short token: add META_APP_ID/META_APP_SECRET to .env and connect again for a 60-day one)")
        print(f"✅ Instagram{'' if login == 'instagram' and not args.page_token else '/Facebook'} saved for {ch}{days}")


def cmd_stats(args):
    from engine import stats_fetch
    stats_fetch.fetch()


def cmd_heal(args):
    """'Heal and Improve the system': the open problems/improvements from the CLOUD memory (read-only copy), plus
    the newest end-of-day review. Nothing is written back to the cloud."""
    import tempfile
    from pathlib import Path
    from engine import heal
    if args.local:
        print(heal.brief())
        return
    from engine.cloud import state
    from engine.cloud.store import Store
    dest = Path(tempfile.mkdtemp(prefix="hh_heal_"))
    state.pull(Store(), root=dest)
    heal.QUEUE = dest / "data" / "state" / "heal_queue.json"
    print(heal.brief())
    rev = dest / "data" / "reviews" / "latest.md"
    print()
    print(rev.read_text(encoding="utf-8")[:6000] if rev.exists() else "(no end-of-day review yet)")
    print(f"(cloud memory copy for investigation: {dest})")


def cmd_quality(args):
    from engine import quality
    quality.run()


def cmd_say(args):
    """Show how the voice will read a line: the rewritten words and the voice's phonemes."""
    from engine.media.say import normalise
    from engine.media.voice import LANG_CODES, _pipeline
    text = " ".join(args.text)
    said = normalise(text, args.lang)
    print("Reads as:", said)
    g2p = _pipeline(LANG_CODES.get(args.lang, "a")).g2p
    print("Phonemes:", g2p(said)[0])


def cmd_doctor(args):
    from engine import doctor
    print(doctor.text(doctor.run()))


def cmd_products(args):
    from engine import products
    if args.action == "book":
        print("Made:", products.activity_book())
    elif args.action == "songs":
        from engine import songs
        print("Made:", songs.album())
    elif args.action == "covers":
        from engine import store_covers
        for pid in (args.ids.split(",") if args.ids else list(store_covers.SPECS)):
            print("Cover:", store_covers.make(pid.strip()))
    elif args.action == "all":
        from engine import product_factory
        for line in product_factory.run():
            print(line)
    elif args.action == "pin":
        from engine import pinterest_post
        pinterest_post.post(args.max)
    elif args.action == "publish":
        from engine import store_publish
        ids = [x.strip() for x in args.ids.split(",")] if args.ids else None
        if args.store == "gumroad":
            store_publish.publish_gumroad(ids)
        else:
            store_publish.publish(args.store, ids, replace=args.replace)


def cmd_bot(args):
    from engine import telegram_bot as tb
    if args.action == "pair":
        print("Send this code to your bot in Telegram:", tb.new_pair_code())
    elif args.action == "digest":
        try:
            tb.digest()
            print("Campaign digest sent to Telegram.")
        except tb.NotConfigured as e:
            print("Telegram not set up yet:", e)
    elif args.action == "report":
        try:
            tb.report()
            print("Morning report sent to Telegram.")
        except tb.NotConfigured as e:
            print("Telegram not set up yet:", e)
    elif args.action == "test":
        print("sent" if tb.notify(args.text or "Test message from HookHouse.") else "not sent (check .env)")
    else:
        from engine.cloud.runner import cloud_enabled
        if cloud_enabled():                     # Telegram talks to the cloud now: the PC helps make videos instead
            print("HookHouse runs in the cloud now; this PC becomes the helper (makes videos while it is on).")
            from engine.cloud import runner
            runner.helper()
        else:
            tb.run()


def cmd_cloud(args):
    """Cloud mode (owner, 13 Nov 2026: run without the PC, managed from the phone)."""
    from engine.cloud import runner
    if args.action == "setup":
        from engine.cloud import setup
        print("Moving HookHouse to the cloud (free, no card)…")
        full = setup.run()
        print(f"Done. Code: https://github.com/{full} · the bot now runs in the cloud; this PC is the helper "
              "(python cli.py bot run, or scripts/helper.cmd).")
    elif args.action == "tick":
        runner.tick(light=args.light)
    elif args.action == "render":
        runner.render(budget_min=float(args.budget))
    elif args.action == "farm":                        # 18 Nov: in-house book pictures on a cloud farm machine
        from engine.cloud import book_farm
        from engine.cloud.store import Store
        print(book_farm.work(Store(), shard=args.shard, shards=args.of, minutes=float(args.budget)))
    elif args.action == "helper":
        runner.helper(once=args.once)
    else:
        from engine.cloud import setup
        env = setup.read_env()
        print("cloud mode:", "ON" if runner.cloud_enabled() else "off", "| repo:", env.get("HOOKHOUSE_REPO") or "-",
              "| missing before setup:", ", ".join(setup.missing(env)) or "nothing")


def main(argv=None):
    p = argparse.ArgumentParser(description="Clip Factory control tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("channels", help="List all channels").set_defaults(fn=cmd_channels)

    b = sub.add_parser("brain", help="AI brain: status or ask")
    b.add_argument("action", choices=["status", "ask"])
    b.add_argument("task", nargs="?", default="writer")
    b.add_argument("prompt", nargs="?", default="Say hello in 5 words.")
    b.set_defaults(fn=cmd_brain)

    c = sub.add_parser("campaign", help="Add, list and manage campaigns")
    c.add_argument("action", choices=["add", "list", "show", "budget", "join", "discover"])
    c.add_argument("--hours", type=int, help="discover: campaigns new in the last N hours (default 48)")
    c.add_argument("--refresh", action="store_true", help="discover: re-check campaigns already seen")
    c.add_argument("id", nargs="?")
    c.add_argument("value", nargs="?")
    c.add_argument("--file", help="Text file with the pasted campaign page")
    c.add_argument("--url")
    c.set_defaults(fn=cmd_campaign)

    m = sub.add_parser("memory", help="Our own memory (RAG)")
    m.add_argument("action", choices=["stats", "add", "search", "seed"])
    m.add_argument("kind_or_text", nargs="?")
    m.add_argument("text", nargs="?")
    m.add_argument("--kind")
    m.add_argument("--channel")
    m.add_argument("--perf", type=float)
    m.add_argument("-k", type=int, default=5)
    m.set_defaults(fn=cmd_memory)

    s = sub.add_parser("schedule", help="Next posting times")
    s.add_argument("market", choices=["US", "IN", "us", "in"])
    s.add_argument("count", nargs="?", type=int, default=4)
    s.set_defaults(fn=cmd_schedule)

    sub.add_parser("licenses", help="Check all licenses allow commercial use").set_defaults(fn=cmd_licenses)

    mk = sub.add_parser("make", help="Make videos: story / clips / brainsnack")
    mk.add_argument("kind", choices=["story", "clips", "brainsnack", "kids"])
    mk.add_argument("--channel", help="channel id or number (story; clips: default hot_take_hq, 14 = stream_clips)")
    mk.add_argument("--topic")
    mk.add_argument("--script", help="use a ready script JSON instead of the AI writer")
    mk.add_argument("--long", action="store_true", help="long horizontal video instead of a Short")
    mk.add_argument("--short", action="store_true", help="kids: a 9:16 mini-episode instead of the full episode")
    mk.add_argument("--source", help="clips: video file or download link")
    mk.add_argument("--campaign", help="clips: campaign id (rules are checked)")
    mk.add_argument("--keep", type=int, default=4)
    mk.add_argument("--format", choices=["spiral", "multiply", "versus", "ladder", "readfast"],
                    help="brainsnack: pick the game format (default: rotate automatically)")
    mk.add_argument("--old", action="store_true", help="brainsnack: the old v2 escaping-balls video")
    mk.set_defaults(fn=cmd_make)

    th = sub.add_parser("thumbs", help="Make 3 thumbnails for a finished video folder")
    th.add_argument("folder")
    th.set_defaults(fn=cmd_thumbs)

    tr = sub.add_parser("trends", help="Today's trend ideas per channel (official feeds, never-topics removed)")
    tr.add_argument("--no-ai", action="store_true", help="skip the AI matching (rough embedding match instead)")
    tr.set_defaults(fn=cmd_trends)

    rv = sub.add_parser("review", help="Build and open the review page (newest video per channel)")
    rv.add_argument("--no-open", action="store_true")
    rv.set_defaults(fn=cmd_review)

    pt = sub.add_parser("pitch", help="Retainer pitch kit: prospects, personalised pitches, media kit, pipeline")
    pt.add_argument("action", choices=["import", "add", "list", "make", "status", "kit"])
    pt.add_argument("id", nargs="?", help="prospect id (make/status)")
    pt.add_argument("value", nargs="?", help="status: new|pitched|replied|trial|client|lost")
    pt.add_argument("--name")
    pt.add_argument("--kind")
    pt.add_argument("--niche")
    pt.add_argument("--url")
    pt.add_argument("--notes")
    pt.set_defaults(fn=cmd_pitch)

    db = sub.add_parser("dashboard", help="Control room: stats, channel progress, jobs, money, to-dos, learnings")
    db.add_argument("--no-open", action="store_true")
    db.add_argument("--watch", action="store_true", help="rebuild every 2 minutes")
    db.set_defaults(fn=cmd_dashboard)

    sub.add_parser("payers", help="Who pays us: tiers and exposure caps").set_defaults(fn=cmd_payers)

    sf = sub.add_parser("safety", help="Check a campaign, or screen a brand-deal email/DM saved as text")
    sf.add_argument("action", choices=["campaign", "offer"])
    sf.add_argument("target", help="campaign id, or a text file with the email/DM")
    sf.add_argument("--sender", help="offer: sender address")
    sf.add_argument("--brand-domain", help="offer: the brand's real website domain")
    sf.add_argument("--attachment", action="append", help="offer: attachment file name (repeatable)")
    sf.set_defaults(fn=cmd_safety)

    lg = sub.add_parser("ledger", help="Money tracking: add an entry, change a payer tier, or show the report")
    lg.add_argument("action", choices=["add", "report", "tier"])
    lg.add_argument("payer", nargs="?", help="payer id from config/payers.yaml")
    lg.add_argument("stage", nargs="?", help="add: tracked/credited/settled/withdraw_requested/sent/bank_received/"
                                             "reversed/written_off; tier: blocked/probation/trusted")
    lg.add_argument("--usd", type=float)
    lg.add_argument("--inr", type=float, help="rupees (for bank_received: the amount that actually arrived)")
    lg.add_argument("--fx-mid", type=float, help="mid-market USD/INR on that day")
    lg.add_argument("--fx", type=float, help="rate you actually got")
    lg.add_argument("--fee", type=float, help="fee in USD")
    lg.add_argument("--ref", help="bank reference / UTR")
    lg.add_argument("--purpose", help="purpose code on the foreign payment")
    lg.add_argument("--fira", help="path to the FIRA / payment statement")
    lg.add_argument("--note")
    lg.add_argument("--domestic", action="store_true", help="Indian-rupee income (not foreign)")
    lg.set_defaults(fn=cmd_ledger)

    cn = sub.add_parser("connect", help="Week 3: connect a channel's YouTube or Instagram/Facebook account")
    cn.add_argument("service", choices=["youtube", "meta", "gmail"])
    cn.add_argument("--channel", help="channel id or number (youtube / meta)")
    cn.add_argument("--ig-user-id")
    cn.add_argument("--page-id")
    cn.add_argument("--token")
    cn.add_argument("--page-token")
    cn.add_argument("--instagram-login", action="store_true",
                    help="token from 'Instagram API with Instagram Login' (no Facebook Page needed; renews itself)")
    cn.set_defaults(fn=cmd_connect)

    st = sub.add_parser("stats", help="Fetch views/watch time for posted videos (YouTube + Instagram)")
    st.add_argument("action", choices=["fetch"])
    st.set_defaults(fn=cmd_stats)

    qc = sub.add_parser("quality", help="Quality scorecard for ALL channels: sound, first/last frame, colour, length, pace")
    qc.set_defaults(fn=cmd_quality)
    sy = sub.add_parser("say", help="How the voice reads a line (numbers, money, names): python cli.py say --lang hi ...")
    sy.add_argument("text", nargs="+")
    sy.add_argument("--lang", default="en", choices=["en", "en-gb", "hi"])
    sy.set_defaults(fn=cmd_say)
    dc = sub.add_parser("doctor", help="Live check of every connection (read-only): Telegram, YouTube, Meta, Dailymotion, PC")
    dc.set_defaults(fn=cmd_doctor)
    pr = sub.add_parser("products", help="Sellable products: book | songs | covers (store covers) | publish (list on our store, automated)")
    pr.add_argument("action", choices=["book", "songs", "covers", "publish", "pin", "all"])
    pr.add_argument("--max", type=int, default=2, help="pin: how many pins this run")
    pr.add_argument("--store", default="payhip", help="publish: which store")
    pr.add_argument("--ids", help="covers/publish: only these product ids (comma-separated)")
    pr.add_argument("--replace", action="store_true", help="publish: re-list products already in the store")
    pr.set_defaults(fn=cmd_products)
    bt = sub.add_parser("bot", help="Telegram bot: run (listen) | digest | report | pair | test")
    bt.add_argument("action", choices=["run", "digest", "report", "pair", "test"])
    bt.add_argument("text", nargs="?")
    bt.set_defaults(fn=cmd_bot)

    cl = sub.add_parser("cloud", help="Cloud mode: setup (one time) | tick | render | helper | status")
    cl.add_argument("action", choices=["setup", "tick", "render", "helper", "status", "farm"])
    cl.add_argument("--shard", type=int, default=0, help="farm: this machine's number (0..of-1)")
    cl.add_argument("--of", type=int, default=1, help="farm: how many farm machines run together")
    cl.add_argument("--budget", default="40", help="render: minutes to spend")
    cl.add_argument("--once", action="store_true", help="helper: one round, then stop")
    cl.add_argument("--light", action="store_true", help="tick: only the Telegram inbox (runs started by a message)")
    cl.set_defaults(fn=cmd_cloud)

    pb = sub.add_parser("publish", help="Upload APPROVED videos (dry run unless --live)")
    pb.add_argument("--week", help="Monday of the week (default: latest)")
    pb.add_argument("--live", action="store_true", help="really upload (needs connected accounts)")
    pb.set_defaults(fn=cmd_publish)

    wk = sub.add_parser("week", help="Week-ahead batch: plan, make, review/approve, status")
    wk.add_argument("action", choices=["plan", "make", "review", "status"])
    wk.add_argument("--start", help="Monday of the week (YYYY-MM-DD); default: next Monday / latest plan")
    wk.add_argument("--channels", help="plan: only these channels (ids or numbers, comma-separated)")
    wk.add_argument("--ids", help="make: only these item ids (comma-separated)")
    wk.add_argument("--lan", action="store_true", help="review: also reachable from your phone on the same Wi-Fi")
    wk.add_argument("--port", type=int, default=8765)
    wk.add_argument("--no-open", action="store_true")
    wk.set_defaults(fn=cmd_week)

    hl = sub.add_parser("heal", help="Heal and Improve: open problems + improvements from the cloud memory")
    hl.add_argument("--local", action="store_true", help="this PC's own queue instead of the cloud copy")
    hl.set_defaults(fn=cmd_heal)

    args = p.parse_args(argv)
    if args.cmd == "memory":
        # `memory add <kind> <text>` / `memory search <text>`
        if args.action == "add":
            args.kind, args.text = args.kind_or_text, args.text
        elif args.action == "search":
            args.text = args.kind_or_text
    if args.cmd == "campaign" and args.action == "add" and not args.file:
        p.error("campaign add needs --file")
    _keep_awake(args.cmd in ("make", "week", "publish", "trends"))
    args.fn(args)


def _keep_awake(on: bool) -> None:
    """Windows: don't sleep while a render/batch runs (a sleeping PC killed renders at 02:24 on 11 Nov).
    This laptop uses Modern Standby, which ignores 'system required' once the screen goes off (renders paused
    14:03-15:10 on 11 Nov), so the display is kept on too. Released automatically when this process ends.
    Closing the lid still sleeps the PC."""
    if not on or sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
    except Exception:  # noqa: BLE001 - never block a render over this
        pass


if __name__ == "__main__":
    settings()  # loads .env
    main()
