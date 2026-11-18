"""Small local database (SQLite) for campaigns and account stats.
Later this is mirrored to the Google Sheet so you can see it on your phone."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .config import ROOT, settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL,
    score REAL, updated REAL);
CREATE TABLE IF NOT EXISTS account_stats (
    channel_id TEXT, platform TEXT, us_pct REAL, tier1_pct REAL, followers INTEGER, updated REAL,
    PRIMARY KEY (channel_id, platform));
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or ROOT / settings()["database"]["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def save_campaign(conn, campaign: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO campaigns(id, data, status, score, updated) VALUES (?,?,?,?,?)",
                 (campaign["id"], json.dumps(campaign, ensure_ascii=False), campaign.get("status", "active"),
                  campaign.get("score"), time.time()))
    conn.commit()


def get_campaign(conn, campaign_id: str) -> dict | None:
    row = conn.execute("SELECT data FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_campaigns(conn, status: str | None = None) -> list[dict]:
    sql, params = "SELECT data FROM campaigns", []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    return [json.loads(r[0]) for r in conn.execute(sql + " ORDER BY score DESC", params).fetchall()]


def save_account_stats(conn, channel_id: str, platform: str, us_pct: float | None,
                       tier1_pct: float | None, followers: int | None = None) -> None:
    conn.execute("INSERT OR REPLACE INTO account_stats VALUES (?,?,?,?,?,?)",
                 (channel_id, platform, us_pct, tier1_pct, followers, time.time()))
    conn.commit()


def get_account_stats(conn, channel_id: str, platform: str) -> dict | None:
    row = conn.execute("SELECT us_pct, tier1_pct, followers, updated FROM account_stats "
                       "WHERE channel_id=? AND platform=?", (channel_id, platform)).fetchone()
    if not row:
        return None
    return {"us_pct": row[0], "tier1_pct": row[1], "followers": row[2], "updated": row[3]}
