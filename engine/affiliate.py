"""Affiliate links: an income line from day one that doesn't need YouTube monetisation
(research: research_notes/Channel growth and earnings plan/github_money_repos_2026-11-10.md, point 4).

- Off until the owner adds their own Associate tag to .env (AMAZON_IN_TAG for Indian channels, AMAZON_COM_TAG for
  US channels). Accounts are in the owner's name, as always.
- One relevant link per video: "books about <the video's main subject>" (the subject = its first Wikipedia source),
  plus the disclosure line the programme requires.
- Never on Made for Kids videos (COPPA, and YouTube's "heavily promotional" rule for kids), never on clip channels
  (campaign rules), and never for never-topics.
"""
from __future__ import annotations

import os
from urllib.parse import quote_plus

from .policy import topic_flags

STORES = {"amazon_in": ("https://www.amazon.in/s?k={q}&tag={tag}", "AMAZON_IN_TAG"),
          "amazon_com": ("https://www.amazon.com/s?k={q}&tag={tag}", "AMAZON_COM_TAG")}
DISCLOSURE = "As an Amazon Associate we earn from qualifying purchases, at no extra cost to you."


def subject(script: dict) -> str:
    srcs = [s for s in script.get("sources") or [] if s]
    return (srcs[0].split("wiki/")[-1].replace("_", " ").strip() if srcs else "") or (script.get("title") or "")


def links(channel: dict, script: dict) -> list[str]:
    """Description lines (link + disclosure), or [] when off / not allowed."""
    cfg = channel.get("affiliate") or {}
    if not cfg or channel.get("made_for_kids") or channel.get("type") in ("clips", "kids"):
        return []
    store = STORES.get(cfg.get("store", ""))
    if not store:
        return []
    url_t, env = store
    tag = os.environ.get(env, "").strip()
    subj = subject(script)
    if not tag or not subj or topic_flags(f"{subj} {script.get('title', '')}", mode="topic"):
        return []
    label = cfg.get("label", "Books about {subject}").format(subject=subj)
    query = cfg.get("query", "{subject} book").format(subject=subj)
    return [f"{label}: {url_t.format(q=quote_plus(query), tag=quote_plus(tag))}", cfg.get("disclosure", DISCLOSURE)]
