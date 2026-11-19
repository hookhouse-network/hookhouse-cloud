"""Campaign safety and payout tracking. Rule: every payer is unproven until money lands in the bank.

- check_campaign(): blocks banned categories (gambling, forex, crypto presales, adult, stock tips),
  RBI alert-list brands, unknown or crypto-only payers and suspicious terms, before we join.
- check_submission(): the 30-minute submit window, reused edits, ad-disclosure length, required tags.
- Ledger: every money movement (tracked -> credited -> settled -> withdrawn -> bank received), overdue
  ageing, exposure caps per payer, FX/fee checks, FIRA paperwork, FEMA 9-month limit, GST threshold.
- screen_offer(): checks "brand deal" emails/DMs for phishing and malware patterns.
Source: research_notes/Channel growth and earnings plan/campaign_payments_fraud.md (10 Nov 2026).
"""
from __future__ import annotations

import difflib
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .config import CONFIG_DIR, ROOT

RBI_LIST = ROOT / "data" / "rbi_alert_list.txt"     # one entity or domain per line (refresh monthly from rbi.org.in)

SCHEMA = """
CREATE TABLE IF NOT EXISTS payer_state (
    payer_id TEXT PRIMARY KEY, tier TEXT, first_bank_receipt_at REAL, on_time INTEGER DEFAULT 0,
    late INTEGER DEFAULT 0, updated REAL);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT, payer_id TEXT, account TEXT, post_url TEXT,
    posted_at REAL, submitted_at REAL, edit_hash TEXT, disclosure_s REAL, video_s REAL,
    status TEXT DEFAULT 'submitted', appeal_used INTEGER DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id INTEGER, campaign_id TEXT, kind TEXT,
    captured_at REAL, sha256 TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT, payer_id TEXT, submission_id INTEGER, stage TEXT,
    amount_usd REAL, amount_inr_expected REAL, amount_inr_received REAL, fx_mid REAL, fx_effective REAL,
    fee_usd REAL, expected_by REAL, occurred_at REAL, ref TEXT, purpose_code TEXT, fira_path TEXT,
    tax_tag TEXT, is_foreign INTEGER DEFAULT 1, notes TEXT);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, sender TEXT, claimed_brand TEXT, verdict TEXT,
    flags TEXT, received_at REAL, verified_via TEXT);
"""
STAGES = ["tracked", "credited", "settled", "withdraw_requested", "sent", "bank_received", "reversed", "written_off"]
OPEN_STAGES = {"credited", "settled", "withdraw_requested", "sent"}

BANNED = {
    "political or advocacy campaign (never-topic: politics)": [
        r"#free[a-z]{3,}", r"\bpolitical\b", r"\bpolitician", r"\belection",
        r"\bvote for\b", r"\bget out the vote\b", r"\bpetition\b", r"\badvocacy\b", r"\bactivis[mt]",
        r"\bcampaign for (president|governor|senate|congress|mayor|parliament)", r"\bsuper ?pac\b"],
    "gambling or betting (India's 2025 online gaming law)": [
        r"\bcasino", r"\bslots?\b", r"sportsbook", r"\bbetting\b", r"\bbet\b", r"\bodds\b", r"sweepstakes?",
        r"\bsweeps\b", r"\bstake\.com", r"\bstake\b", r"roobet", r"prediction market", r"\bpoker\b", r"rummy",
        r"fantasy (cricket|sports|league)", r"real[- ]money gam"],
    "forex / CFD / prop trading (RBI)": [
        r"\bforex\b", r"\bfx trading", r"\bcfds?\b", r"\bpips?\b", r"leverage", r"funded account", r"prop firm",
        r"proprietary trading", r"\bbroker\b", r"binary options?"],
    "crypto presale / token scheme": [
        r"token launch", r"\bairdrop", r"pre-?sale", r"\bico\b", r"memecoin", r"meme coin", r"\$[A-Z]{2,6}\b token"],
    "adult content": [r"\badult\b", r"\bnsfw\b", r"onlyfans", r"\bescort", r"18\+ (content|site)"],
    "stock tips / investment advice (SEBI)": [
        r"target price", r"buy call", r"stock tips?", r"intraday tips?", r"multibagger", r"guaranteed returns?"],
    "medical / health claims": [r"\bcure[sd]?\b", r"weight[- ]loss (pill|drug)", r"miracle (cure|supplement)"],
}
TERMS_FLAGS = {
    "asks for a fee or deposit": r"(registration|joining|security|activation) fee|pay (a |the )?deposit|upfront (fee|payment)",
    "guarantees earnings": r"guaranteed (earnings|income|payout)|earn \$?\d+[k]? (a|per) (day|week) guaranteed",
    "vague rejection terms": r"(reject|disqualif)\w* (any|at our sole) (submission|discretion)",
}
BAD_DOMAINS = {"joinmatchy", "matchyjoin", "scouty", "mytubive", "creoventura", "youtube-plus"}
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "protonmail.com", "icloud.com",
             "aol.com", "mail.com", "gmx.com", "yandex.com", "rediffmail.com"}
OFFER_WORDS = ["fee", "deposit", "crypto", "wallet", "verify your channel", "private video", "policy update",
               "sign in with google", "password", "download the contract", "brief.zip", "gift card", "usdt"]
RISKY_ATTACH = re.compile(r"\.(exe|scr|bat|cmd|js|vbs|ps1|msi|lnk|iso|img|jar|hta|zip|rar|7z)$", re.I)


# ---------- payers ----------

def payers() -> dict[str, dict]:
    path = CONFIG_DIR / "payers.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def _host(url_or_domain: str) -> str:
    s = (url_or_domain or "").strip().lower()
    if "://" not in s:
        s = "http://" + s
    host = urlparse(s).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def payer_for_url(url: str) -> tuple[str | None, dict | None]:
    host = _host(url)
    for pid, p in payers().items():
        if any(_on_domain(host, d) for d in p.get("official_domains") or []):
            return pid, p
    return None, None


def connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    if conn is None:
        from .db import connect as db_connect
        conn = db_connect()
    conn.executescript(SCHEMA)
    return conn


def payer_tier(conn, payer_id: str) -> str:
    row = conn.execute("SELECT tier FROM payer_state WHERE payer_id=?", (payer_id,)).fetchone()
    if row and row[0]:
        return row[0]
    return (payers().get(payer_id) or {}).get("tier", "probation")


def exposure_cap_inr(conn, payer_id: str) -> float:
    tier = payer_tier(conn, payer_id)
    if tier == "blocked":
        return 0.0
    if tier == "trusted":
        week = conn.execute("SELECT COALESCE(SUM(amount_inr_expected),0) FROM ledger WHERE payer_id=? AND "
                            "stage='credited' AND occurred_at>?", (payer_id, time.time() - 7 * 86400)).fetchone()[0]
        return max(25_000.0, float(week))
    p = payers().get(payer_id) or {}
    min_inr = (p.get("min_withdrawal_inr") or 0) or (p.get("min_withdrawal_usd") or 0) * 85
    return max(2_000.0, min_inr * 1.2)


def outstanding_inr(conn, payer_id: str | None = None) -> float:
    """Money earned but not yet in our bank: credited/settled/requested/sent, minus what already arrived."""
    sql = ("SELECT payer_id, stage, COALESCE(amount_inr_expected,0), COALESCE(amount_inr_received,0), ref FROM ledger"
           + (" WHERE payer_id=?" if payer_id else ""))
    rows = conn.execute(sql, (payer_id,) if payer_id else ()).fetchall()
    credited = sum(r[2] for r in rows if r[1] == "credited")
    received = sum(r[3] or r[2] for r in rows if r[1] == "bank_received")
    reversed_ = sum(r[2] for r in rows if r[1] in ("reversed", "written_off"))
    return max(0.0, credited - received - reversed_)


def can_submit(conn, payer_id: str) -> tuple[bool, str]:
    if (payers().get(payer_id) or {}).get("type") == "native_program":
        return True, "Platform program (ad revenue): no exposure cap"
    tier = payer_tier(conn, payer_id)
    if tier == "blocked":
        return False, f"{payer_id} is blocked"
    out, cap = outstanding_inr(conn, payer_id), exposure_cap_inr(conn, payer_id)
    if out >= cap:
        return False, f"Exposure cap reached for {payer_id}: ₹{out:,.0f} owed ≥ cap ₹{cap:,.0f}. Withdraw first."
    total = outstanding_inr(conn)
    if total > 10_000 and out / total > 0.40:
        return False, f"{payer_id} holds {out / total:.0%} of all money owed to us (limit 40%). Spread the work."
    return True, f"OK: ₹{out:,.0f} owed of ₹{cap:,.0f} cap ({tier})"


# ---------- campaign gate ----------

def classify_banned(text: str) -> list[str]:
    t = (text or "").lower()
    hits = []
    for label, patterns in BANNED.items():
        found = [p for p in patterns if re.search(p, t, re.I)]
        if found:
            clean = [f.replace(chr(92) + "b", "") for f in found[:3]]       # drop the regex word-boundary marks
            hits.append(f"{label}: matched {', '.join(clean)}")
    from .policy import topic_flags
    for cat in topic_flags(text or "", mode="campaign"):
        if not any(cat.split("_")[0] in h.lower() for h in hits):
            hits.append(f"never-topic: {cat.replace('_', ' ')}")
    return hits


def rbi_hits(names: list[str]) -> list[str]:
    if not RBI_LIST.exists():
        return []
    entries = [ln.strip().lower() for ln in RBI_LIST.read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.startswith("#")]
    hits = []
    for name in filter(None, (n.lower().strip() for n in names)):
        for e in entries:
            if e in name or name in e or difflib.SequenceMatcher(None, name, e).ratio() >= 0.86:
                hits.append(f"'{name}' matches RBI alert-list entry '{e}'")
    return hits


def check_campaign(c: dict, conn=None) -> dict:
    """ALLOW / REVIEW / BLOCK with reasons. Plugs in before campaigns.score_campaign()."""
    reasons_block, reasons_review = [], []
    blob = " ".join(str(c.get(k) or "") for k in ("name", "brand", "brand_name", "description", "rules_text",
                                                   "raw_text", "category", "url"))
    blob += " " + " ".join(map(str, c.get("rules") or []))
    reasons_block += classify_banned(blob)
    reasons_block += rbi_hits([c.get("brand") or c.get("brand_name") or "", c.get("name") or "",
                               _host(c.get("brand_domain") or "")])
    if re.search(r"forex|trading|broker|prop firm|crypto", blob, re.I) and not reasons_block:
        reasons_review.append("Trading/crypto-related brand: not being on the RBI list does not mean it is authorised")
    pid, p = payer_for_url(c.get("url") or "")
    if not pid:
        reasons_review.append(f"Unknown payer for {_host(c.get('url') or '') or 'missing link'}: add it to "
                              "config/payers.yaml after checking it (company, terms, India payout)")
    else:
        tier = payer_tier(connect(conn), pid) if conn is not None else p.get("tier", "probation")
        if tier == "blocked":
            reasons_block.append(f"Payer '{p['name']}' is blocked: {p.get('notes', '')}".strip())
        if p.get("crypto_only"):
            reasons_block.append("Crypto-only payouts: no FIRA (FEMA) and 30% crypto tax")
    for label, pat in TERMS_FLAGS.items():
        if re.search(pat, blob, re.I):
            reasons_block.append(f"Terms: {label}") if "fee" in label else reasons_review.append(f"Terms: {label}")
    cpm = c.get("cpm_usd")
    if cpm and cpm > 3 * 1.25 and not (c.get("brand") or c.get("brand_name")):
        reasons_review.append(f"Pays ${cpm}/1k (3x the board median) with no named brand")
    if c.get("keep_up_days") and c["keep_up_days"] > 30:
        reasons_review.append(f"Posts must stay up {c['keep_up_days']} days (over 30)")
    verdict = "BLOCK" if reasons_block else "REVIEW" if reasons_review else "ALLOW"
    return {"verdict": verdict, "block": reasons_block, "review": reasons_review, "payer_id": pid}


# ---------- submissions ----------

def video_hash(path: Path, samples: int = 8) -> str:
    """Perceptual hash of a video (difference hash of evenly spaced frames). Same edit -> same hash."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    bits = []
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((k + 0.5) * n / samples))
        ok, f = cap.read()
        if not ok:
            continue
        g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (9, 8), interpolation=cv2.INTER_AREA)
        bits.extend((g[:, 1:] > g[:, :-1]).flatten().tolist())
    cap.release()
    return hex(int("".join("1" if b else "0" for b in bits) or "0", 2))[2:]


def disclosure_needed_s(video_s: float) -> float:
    """ASCI: for videos up to 2 minutes the ad label must stay on screen for a third of the video (min 3 s)."""
    return max(3.0, video_s / 3) if video_s <= 120 else 3.0


def check_submission(conn, sub: dict, campaign: dict | None = None) -> list[str]:
    issues = []
    deadline = (payers().get(sub.get("payer_id") or "") or {}).get("submit_deadline_min")
    if deadline and sub.get("posted_at") and sub.get("submitted_at"):
        delay = (sub["submitted_at"] - sub["posted_at"]) / 60
        if delay > deadline:
            issues.append(f"Submitted {delay:.0f} min after posting (limit {deadline} min)")
    if sub.get("edit_hash"):
        row = conn.execute("SELECT campaign_id FROM submissions WHERE edit_hash=? AND campaign_id!=?",
                           (sub["edit_hash"], sub.get("campaign_id"))).fetchone()
        if row:
            issues.append(f"This exact edit was already submitted to campaign {row[0]}")
    if campaign and campaign.get("is_paid_promotion", True) and sub.get("video_s"):
        need = disclosure_needed_s(sub["video_s"])
        if (sub.get("disclosure_s") or 0) < need:
            issues.append(f"Ad label shown {sub.get('disclosure_s') or 0:.0f}s; ASCI needs {need:.0f}s from the start")
    caption = (sub.get("caption") or "").lower()
    for tag in (campaign or {}).get("required_tags") or []:
        if tag.lower() not in caption:
            issues.append(f"Missing required tag {tag}")
    return issues


EVIDENCE_SCHEDULE_H = [1, 24, 72, 168, 336, 720]      # analytics screenshots after posting (hours)


# ---------- ledger ----------

def ledger_add(conn, payer_id: str, stage: str, amount_usd: float = 0.0, amount_inr: float | None = None,
               fx_mid: float | None = None, fx_effective: float | None = None, fee_usd: float | None = None,
               ref: str = "", purpose_code: str = "", fira_path: str = "", occurred_at: float | None = None,
               submission_id: int | None = None, notes: str = "", foreign: bool = True) -> int:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    p = payers().get(payer_id) or {}
    occurred_at = occurred_at or time.time()
    expected = None
    if stage == "credited":
        expected = occurred_at + 86400 * ((p.get("expected_settle_days") or 30) + (p.get("expected_withdraw_days") or 7))
    inr_expected = amount_inr if (amount_inr is not None and stage != "bank_received") else (
        amount_usd * fx_mid if fx_mid else amount_usd * 85.0 if amount_usd else None)
    received = amount_inr if stage == "bank_received" else None
    cur = conn.execute(
        "INSERT INTO ledger(payer_id, submission_id, stage, amount_usd, amount_inr_expected, amount_inr_received, "
        "fx_mid, fx_effective, fee_usd, expected_by, occurred_at, ref, purpose_code, fira_path, tax_tag, is_foreign, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (payer_id, submission_id, stage, amount_usd, inr_expected, received, fx_mid, fx_effective, fee_usd, expected,
         occurred_at, ref, purpose_code, fira_path, "vda" if (p.get("crypto_only")) else
         ("services_export" if foreign else "domestic_services"), int(foreign), notes))
    if stage == "bank_received":
        _mark_receipt(conn, payer_id, occurred_at)
    conn.commit()
    return cur.lastrowid


def _mark_receipt(conn, payer_id: str, at: float) -> None:
    row = conn.execute("SELECT first_bank_receipt_at, on_time FROM payer_state WHERE payer_id=?", (payer_id,)).fetchone()
    first = row[0] if row and row[0] else at
    on_time = (row[1] if row else 0) + 1
    tier = payer_tier(conn, payer_id)
    if tier == "probation" and on_time >= 3:
        tier = "trusted"                               # three real bank receipts -> trusted
    conn.execute("INSERT OR REPLACE INTO payer_state(payer_id, tier, first_bank_receipt_at, on_time, late, updated) "
                 "VALUES (?,?,?,?,COALESCE((SELECT late FROM payer_state WHERE payer_id=?),0),?)",
                 (payer_id, tier, first, on_time, payer_id, time.time()))


def set_tier(conn, payer_id: str, tier: str) -> None:
    if tier not in ("blocked", "probation", "trusted"):
        raise ValueError("tier must be blocked, probation or trusted")
    conn.execute("INSERT OR REPLACE INTO payer_state(payer_id, tier, first_bank_receipt_at, on_time, late, updated) "
                 "VALUES (?,?,(SELECT first_bank_receipt_at FROM payer_state WHERE payer_id=?),"
                 "COALESCE((SELECT on_time FROM payer_state WHERE payer_id=?),0),"
                 "COALESCE((SELECT late FROM payer_state WHERE payer_id=?),0),?)",
                 (payer_id, tier, payer_id, payer_id, payer_id, time.time()))
    conn.commit()


def alerts(conn, now: float | None = None) -> list[tuple[str, str]]:
    """(severity, message) for overdue money, exposure, FX/fees, paperwork, FEMA and GST."""
    now = now or time.time()
    out = []
    rows = conn.execute("SELECT id, payer_id, stage, amount_usd, amount_inr_expected, amount_inr_received, fx_mid, "
                        "fx_effective, fee_usd, expected_by, occurred_at, fira_path, is_foreign FROM ledger").fetchall()
    received_refs = {r[1] for r in rows if r[2] == "bank_received"}
    for (lid, pid, stage, usd, inr_exp, inr_rec, mid, eff, fee, exp_by, at, fira, foreign) in rows:
        if stage == "credited" and exp_by and now > exp_by:
            days = (now - exp_by) / 86400
            paid_since = conn.execute("SELECT COUNT(*) FROM ledger WHERE payer_id=? AND stage='bank_received' AND "
                                      "occurred_at>?", (pid, at)).fetchone()[0]
            if not paid_since:
                sev = "HIGH" if days > 7 else "MEDIUM"
                out.append((sev, f"{pid}: ₹{inr_exp or 0:,.0f} credited {datetime.fromtimestamp(at):%d %b} is "
                                 f"{days:.0f} days overdue"))
        if stage == "bank_received":
            if mid and eff and eff < mid * 0.975:
                out.append(("MEDIUM", f"{pid}: exchange rate {eff:.2f} is {(1 - eff / mid):.1%} below mid-market {mid:.2f}"))
            if foreign and not fira and now - at > 15 * 86400:
                out.append(("MEDIUM", f"{pid}: no FIRA/payment statement saved for the receipt of "
                                      f"{datetime.fromtimestamp(at):%d %b} (needed within 15 days)"))
    for pid in {r[1] for r in rows}:
        ok, why = can_submit(conn, pid)
        if not ok:
            out.append(("HIGH", why))
        oldest = conn.execute("SELECT MIN(occurred_at) FROM ledger WHERE payer_id=? AND stage IN ('credited','settled') "
                              "AND is_foreign=1", (pid,)).fetchone()[0]
        if oldest and outstanding_inr(conn, pid) > 0 and now - oldest > 182 * 86400:
            out.append(("CRITICAL", f"{pid}: foreign earnings older than 6 months are still not in India "
                                    "(FEMA limit is 9 months)"))
    fy_start = datetime(datetime.fromtimestamp(now).year if datetime.fromtimestamp(now).month >= 4
                        else datetime.fromtimestamp(now).year - 1, 4, 1).timestamp()
    turnover = conn.execute("SELECT COALESCE(SUM(COALESCE(amount_inr_received, amount_inr_expected)),0) FROM ledger "
                            "WHERE stage='bank_received' AND occurred_at>=?", (fy_start,)).fetchone()[0]
    if turnover >= 2_000_000:
        out.append(("HIGH", f"GST: turnover this financial year is ₹{turnover:,.0f}: register for GST and file an LUT"))
    elif turnover >= 1_500_000:
        out.append(("MEDIUM", f"GST: turnover this financial year is ₹{turnover:,.0f} (registration needed at ₹20 lakh)"))
    return out


def report(conn) -> str:
    lines = ["Money owed to us (by payer):"]
    for pid, p in payers().items():
        out = outstanding_inr(conn, pid)
        got = conn.execute("SELECT COALESCE(SUM(COALESCE(amount_inr_received, amount_inr_expected)),0) FROM ledger "
                           "WHERE payer_id=? AND stage='bank_received'", (pid,)).fetchone()[0]
        if out or got:
            lines.append(f"  {p['name']:<45} owed ₹{out:>10,.0f}   received ₹{got:>10,.0f}   tier {payer_tier(conn, pid)}")
    if len(lines) == 1:
        lines.append("  (nothing recorded yet)")
    al = alerts(conn)
    lines.append("Alerts:" if al else "Alerts: none")
    lines += [f"  [{s}] {m}" for s, m in sorted(al, key=lambda x: ["CRITICAL", "HIGH", "MEDIUM"].index(x[0]))]
    return "\n".join(lines)


# ---------- inbound offers ----------

def _lookalike(host: str, brand_domain: str) -> bool:
    a, b = host.split(".")[0], brand_domain.split(".")[0]
    if a == b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8 or (abs(len(a) - len(b)) <= 2 and
                                                                  sum(x != y for x, y in zip(a, b)) <= 2)


def screen_offer(text: str, sender: str = "", brand_domain: str = "", attachments: list[str] | None = None) -> dict:
    """BLOCK / REVIEW / OK for a brand-deal email or DM. Never opens links or attachments."""
    flags, block = [], []
    t = (text or "").lower()
    sender_domain = sender.split("@")[-1].lower().strip(">") if "@" in sender else ""
    if sender_domain in FREE_MAIL:
        flags.append(f"Sent from a free mailbox ({sender_domain}), not a company domain")
    if brand_domain and sender_domain and not _on_domain(sender_domain, brand_domain.lower()):
        flags.append(f"Sender domain {sender_domain} is not the brand's domain {brand_domain}")
    for url in re.findall(r"https?://[^\s<>\"')]+", text or ""):
        host = _host(url)
        base = host.split(".")[-2] if host.count(".") >= 1 else host
        if any(b in host for b in BAD_DOMAINS):
            block.append(f"Known scam domain: {host}")
        if ("google" in host and "accounts.google.com" not in host and re.search(r"sign.?in|login|oauth", url, re.I)):
            block.append(f"Fake Google sign-in page: {host}")
        if brand_domain and _lookalike(host, brand_domain.lower()):
            block.append(f"Lookalike of {brand_domain}: {host}")
        if re.search(r"bit\.ly|tinyurl|t\.co/|cutt\.ly|rb\.gy|is\.gd", url):
            flags.append(f"Shortened link hides the destination: {url[:60]}")
        _ = base
    for a in attachments or []:
        if RISKY_ATTACH.search(a):
            block.append(f"Risky attachment (program/archive): {a}")
    if re.search(r"password[: ]+\w+", t) and re.search(r"\.(zip|rar|7z)|archive|attachment", t):
        block.append("Password-protected archive: a common malware trick")
    for w in OFFER_WORDS:
        if w in t:
            flags.append(f"Contains '{w}'")
    if t.lstrip().startswith("re:"):
        flags.append("Pretends to be a reply ('Re:') on first contact")
    verdict = "BLOCK" if block else "REVIEW" if flags else "OK"
    return {"verdict": verdict, "block": block, "flags": flags,
            "next_step": "Do not click anything. Contact the brand through the address on its official website."
            if verdict != "OK" else "Still confirm the brand through its official website before signing."}
