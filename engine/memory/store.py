"""Our own memory (RAG). Stores hooks, titles, scripts, playbook notes, campaign
rules and top viral videos, and finds the most similar *winning* examples
before the brain writes anything.

Uses a small multilingual model (English + Hindi) on CPU. If that model is not
available, a simple built-in fallback keeps everything working (lower quality).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

KINDS = ("hook", "title", "script", "playbook", "campaign_rule", "rejection", "viral_example", "fact", "note")


class HashEmbedder:
    """Fallback embedder: no download needed. Word + character-trigram hashing."""
    dim = 512
    name = "hash-fallback"

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            t = text.lower()
            tokens = re.findall(r"\w+", t)
            grams = tokens + [t[i:i + 3] for i in range(max(0, len(t) - 2))]
            for g in grams:
                h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
                out[row, h % self.dim] += 1.0 if (h >> 9) % 2 else -1.0
            norm = np.linalg.norm(out[row])
            if norm:
                out[row] /= norm
        return out


class SentenceEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, only when used
        self.model = SentenceTransformer(model_name, device="cpu")
        self.name = model_name
        self.e5 = "e5" in model_name.lower()
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        if self.e5:
            prefix = "query: " if is_query else "passage: "
            texts = [prefix + t for t in texts]
        return np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)


def make_embedder(model_name: str | None, allow_download: bool = True):
    if model_name and allow_download:
        try:
            return SentenceEmbedder(model_name)
        except Exception as e:  # missing package, no internet, etc.
            print(f"[memory] Using fallback embedder ({e.__class__.__name__}: {e})")
    return HashEmbedder()


@dataclass
class Hit:
    id: int
    kind: str
    channel: str | None
    text: str
    meta: dict
    performance: float | None
    similarity: float
    rank_score: float


class Memory:
    def __init__(self, db_path: Path, embedder=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or HashEmbedder()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL, channel TEXT, text TEXT NOT NULL, meta TEXT,
            performance REAL, embedder TEXT, vector BLOB, created REAL)""")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_kind ON items(kind, channel)")
        self.conn.commit()

    # ---------- writing ----------
    def add(self, kind: str, text: str, channel: str | None = None, meta: dict | None = None,
            performance: float | None = None) -> int:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        vec = self.embedder.encode([text])[0]
        cur = self.conn.execute(
            "INSERT INTO items(kind, channel, text, meta, performance, embedder, vector, created) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (kind, channel, text, json.dumps(meta or {}, ensure_ascii=False), performance,
             self.embedder.name, vec.tobytes(), time.time()))
        self.conn.commit()
        return cur.lastrowid

    def set_performance(self, item_id: int, performance: float) -> None:
        """Record results (e.g. views at 48h) so winners rank higher."""
        self.conn.execute("UPDATE items SET performance=? WHERE id=?", (performance, item_id))
        self.conn.commit()

    def reembed_all(self) -> int:
        """Re-calculate vectors after switching embedding model."""
        rows = self.conn.execute("SELECT id, text FROM items").fetchall()
        for item_id, text in rows:
            vec = self.embedder.encode([text])[0]
            self.conn.execute("UPDATE items SET vector=?, embedder=? WHERE id=?",
                              (vec.tobytes(), self.embedder.name, item_id))
        self.conn.commit()
        return len(rows)

    # ---------- reading ----------
    def search(self, query: str, kind: str | None = None, channel: str | None = None, k: int = 5,
               winner_weight: float = 0.35, include_global: bool = True) -> list[Hit]:
        """Most similar items, boosted by how well they performed.

        rank = similarity * (1 + winner_weight * performance_percentile)
        """
        sql = "SELECT id, kind, channel, text, meta, performance, embedder, vector FROM items WHERE 1=1"
        params: list = []
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if channel:
            sql += " AND (channel=?" + (" OR channel IS NULL)" if include_global else ")")
            params.append(channel)
        rows = [r for r in self.conn.execute(sql, params).fetchall() if r[6] == self.embedder.name]
        if not rows:
            return []
        q = self.embedder.encode([query], is_query=True)[0]
        mat = np.vstack([np.frombuffer(r[7], dtype=np.float32) for r in rows])
        sims = mat @ q
        perfs = [r[5] for r in rows]
        known = sorted(p for p in perfs if p is not None)

        def percentile(p):
            if p is None or not known:
                return 0.0
            return sum(1 for x in known if x <= p) / len(known)

        hits = []
        for r, sim in zip(rows, sims):
            pct = percentile(r[5])
            hits.append(Hit(r[0], r[1], r[2], r[3], json.loads(r[4] or "{}"), r[5], float(sim),
                            float(sim) * (1 + winner_weight * pct)))
        hits.sort(key=lambda h: h.rank_score, reverse=True)
        return hits[:k]

    def context_block(self, query: str, channel: str | None, kinds=("hook", "title", "viral_example", "playbook"),
                      k_each: int = 4) -> str:
        """Ready-to-paste text for prompts: similar winners + playbook notes."""
        lines = []
        for kind in kinds:
            hits = self.search(query, kind=kind, channel=channel, k=k_each)
            if not hits:
                continue
            lines.append("## What is winning for other creators this month (learn the pattern: subject, curiosity gap, "
                         "numbers, wording length; never copy their words)" if kind == "viral_example"
                         else f"## Similar {kind.replace('_', ' ')}s (best first)")
            for h in hits:
                perf = f" — {int(h.performance):,} views" if h.performance is not None else ""
                lines.append(f"- {h.text}{perf}")
        return "\n".join(lines)

    def count(self) -> dict[str, int]:
        return dict(self.conn.execute("SELECT kind, COUNT(*) FROM items GROUP BY kind").fetchall())

    def close(self):
        self.conn.close()


def open_memory(allow_download: bool = True) -> Memory:
    from ..config import ROOT, settings
    cfg = settings()["memory"]
    return Memory(ROOT / cfg["db_path"], make_embedder(cfg.get("embedding_model"), allow_download))
