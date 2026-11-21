// HookHouse shared truth (master plan Phase 1, 20 Nov 2026): one Durable Object with SQLite storage.
// Free plan: 100,000 requests and 100,000 row writes a day. Single-threaded, so writes never interleave.
// Phase 1 = dual-write: the Python ledger (engine/core/ledger.py, SQLite) stays authoritative and mirrors every
// committed row here as a row image keyed by its primary key (idempotent upserts and deletes). The nightly diff
// compares both sides; reads move here only after a clean comparison. Tables = engine/core/ledger.py SCHEMA + kv.
import { DurableObject } from "cloudflare:workers";

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at REAL NOT NULL, type TEXT NOT NULL,
     item TEXT, channel TEXT, worker TEXT, data TEXT)`,
  `CREATE INDEX IF NOT EXISTS ev_type_at ON events(type, at)`,
  `CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
     payload TEXT, state TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 0,
     attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 5, run_after REAL NOT NULL DEFAULT 0,
     lease_owner TEXT, lease_until REAL, created REAL NOT NULL, updated REAL NOT NULL, last_error TEXT, result TEXT)`,
  `CREATE TABLE IF NOT EXISTS checkpoints (item TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
     artifact TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT, updated REAL NOT NULL, PRIMARY KEY (item, stage))`,
  `CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, updated REAL NOT NULL)`,
  // Phase 1 last step (21 Nov): the Telegram bot's working keys move off KV (1,000 free writes a day) to here
  `CREATE TABLE IF NOT EXISTS tkv (k TEXT PRIMARY KEY, v TEXT, expires REAL, updated REAL NOT NULL)`,
];

// Telegram keys allowed in tkv: updates, dashboard commands + their results, card decisions, small counters.
export const TELE_PREFIX = /^(upd|cmd|res|dec|meta):[A-Za-z0-9_:.\-]{1,120}$/;
const TELE_MAX_VALUE = 256 * 1024;

export function validTele(b) {
  if (!b || typeof b.k !== "string" || !TELE_PREFIX.test(b.k)) return false;
  if (b.op === "tput") {
    if (typeof b.v !== "string" || b.v.length > TELE_MAX_VALUE) return false;
    if (b.ttl !== undefined && b.ttl !== null && !(Number(b.ttl) > 0 && Number(b.ttl) <= 30 * 86400)) return false;
  }
  return true;
}

// Allow-list: table -> columns and primary key. Nothing else can be written through the API.
export const TABLES = {
  events: { pk: ["id"], cols: ["id", "at", "type", "item", "channel", "worker", "data"] },
  jobs: { pk: ["id"], cols: ["id", "kind", "key", "payload", "state", "priority", "attempts", "max_attempts",
                             "run_after", "lease_owner", "lease_until", "created", "updated", "last_error", "result"] },
  checkpoints: { pk: ["item", "stage"], cols: ["item", "stage", "status", "artifact", "attempts", "error", "updated"] },
};
const MAX_CHANGES = 500;

export function validChange(ch) {
  const t = TABLES[ch && ch.t];
  if (!t || !["up", "del"].includes(ch.op)) return false;
  const row = ch.op === "up" ? ch.row : ch.key;
  if (!row || typeof row !== "object") return false;
  const allowed = ch.op === "up" ? t.cols : t.pk;
  return Object.keys(row).every(k => allowed.includes(k)) && t.pk.every(k => row[k] !== undefined && row[k] !== null);
}

export class LedgerDO extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    ctx.blockConcurrencyWhile(async () => { for (const s of SCHEMA) this.sql.exec(s); });
  }

  apply(changes) {
    if (!Array.isArray(changes) || changes.length > MAX_CHANGES) throw new Error("bad change list");
    if (!changes.every(validChange)) throw new Error("change outside the allow-list");
    this.ctx.storage.transactionSync(() => {          // all or nothing: a cut-off batch leaves nothing half-written
      for (const ch of changes) {
        const t = TABLES[ch.t];
        if (ch.op === "up") {
          const cols = Object.keys(ch.row);
          this.sql.exec(`INSERT OR REPLACE INTO ${ch.t}(${cols.join(",")}) VALUES (${cols.map(() => "?").join(",")})`,
                        ...cols.map(c => ch.row[c]));
        } else {
          this.sql.exec(`DELETE FROM ${ch.t} WHERE ${t.pk.map(k => `${k}=?`).join(" AND ")}`, ...t.pk.map(k => ch.key[k]));
        }
      }
    });
    return { applied: changes.length };
  }

  stats() {
    const out = {};
    for (const t of Object.keys(TABLES)) {
      const r = this.sql.exec(`SELECT count(*) AS n FROM ${t}`).one();
      out[t] = r.n;
    }
    out.tkv = this.sql.exec(`SELECT count(*) AS n FROM tkv`).one().n;     // Telegram keys (Phase 1 last step)
    return out;
  }

  rows(table, after, limit) {                           // for the diff check: ordered by primary key
    const t = TABLES[table];
    if (!t) throw new Error("unknown table");
    const n = Math.min(Number(limit) || 500, 2000);
    if (table === "checkpoints") {
      const [item, stage] = Array.isArray(after) ? after : ["", ""];
      return this.sql.exec(`SELECT * FROM checkpoints WHERE (item, stage) > (?, ?) ORDER BY item, stage LIMIT ?`,
                           item, stage, n).toArray();
    }
    return this.sql.exec(`SELECT * FROM ${table} WHERE id > ? ORDER BY id LIMIT ?`, Number(after) || 0, n).toArray();
  }

  // ---- Telegram keys (tkv): get / put with a time-to-live / delete / list by prefix. Expired rows read as missing.
  tele(b) {
    const now = Date.now() / 1000;
    if (b.op === "tlist") {
      const p = String(b.prefix || "");
      if (!/^(upd|cmd|res|dec|meta):/.test(p)) throw new Error("prefix outside the allow-list");
      const n = Math.min(Number(b.limit) || 1000, 1000);
      return { keys: this.sql.exec(`SELECT k FROM tkv WHERE k >= ? AND k < ? AND (expires IS NULL OR expires >= ?)
                                    ORDER BY k LIMIT ?`, p, p + "￿", now, n).toArray().map(r => r.k) };
    }
    if (!validTele(b)) throw new Error("tele key or value outside the allow-list");
    if (b.op === "tget") {
      const r = this.sql.exec(`SELECT v, expires FROM tkv WHERE k = ?`, b.k).toArray()[0];
      return { v: r && !(r.expires && r.expires < now) ? r.v : null };
    }
    if (b.op === "tput") {
      this.sql.exec(`INSERT OR REPLACE INTO tkv(k, v, expires, updated) VALUES (?, ?, ?, ?)`, b.k, b.v,
                    b.ttl ? now + Number(b.ttl) : null, now);
      if (Math.random() < 0.02) this.sql.exec(`DELETE FROM tkv WHERE expires IS NOT NULL AND expires < ?`, now);
      return { ok: 1 };
    }
    if (b.op === "tdel") {
      this.sql.exec(`DELETE FROM tkv WHERE k = ?`, b.k);
      return { ok: 1 };
    }
    throw new Error("unknown tele op");
  }

  async fetch(request) {
    let b;
    try { b = await request.json(); } catch (e) { return Response.json({ error: "bad json" }, { status: 400 }); }
    try {
      if (b.op === "apply") return Response.json(this.apply(b.changes));
      if (b.op === "stats") return Response.json(this.stats());
      if (b.op === "rows") return Response.json({ rows: this.rows(b.table, b.after, b.limit) });
      if (["tget", "tput", "tdel", "tlist"].includes(b.op)) return Response.json(this.tele(b));
      return Response.json({ error: "unknown op" }, { status: 400 });
    } catch (e) {
      return Response.json({ error: String(e && e.message || e) }, { status: 400 });
    }
  }
}

// HMAC-SHA256(HH_API_KEY, `${ts}.${body}`), timestamp within 5 minutes (replays inside the window are harmless:
// every change is an idempotent upsert/delete).
export async function apiAuthorized(request, env, body, hmacHex) {
  const key = env.HH_API_KEY || "";
  if (key.length < 24) return false;
  const ts = Number(request.headers.get("x-hh-ts") || 0);
  const sig = request.headers.get("x-hh-sig") || "";
  if (!ts || Math.abs(Date.now() / 1000 - ts) > 300) return false;
  const want = await hmacHex(key, `${ts}.${body}`);
  return sig.length === want.length && sig === want;
}

export async function api(request, env, url, hmacHex) {
  if (request.method !== "POST" || url.pathname !== "/api/ledger") return new Response("no", { status: 404 });
  const body = await request.text();
  if (body.length > 1_000_000) return new Response("too big", { status: 413 });
  if (!(await apiAuthorized(request, env, body, hmacHex))) return new Response("no", { status: 401 });
  const stub = env.LEDGER.get(env.LEDGER.idFromName("main"));
  return stub.fetch("https://ledger/", { method: "POST", body });
}
