// HookHouse scheduler (master plan Phase 2, section 5.3): one shared job queue for every worker (PC makers, GitHub
// tick/render runs, the Cloudflare Worker). Pure module: it only talks to SQLite through two functions, so the
// LedgerDO (Durable Object SQLite) and the tests (Node's built-in node:sqlite) run the very same code.
//   q(sql, ...args)   -> array of row objects        run(sql, ...args) -> number of rows changed
// Jobs: priority class P0..P4 (0 = owner taps/posting ... 4 = maintenance), deadline (EDF with slack inside a class),
// capabilities a worker must have, preferred worker kinds, fallback rules for other kinds, per-class slots per worker
// (bulkheads). Every lease carries an EPOCH: complete/fail/heartbeat must present it, so a worker that slept through
// its lease cannot finish a job someone else took over (no video is ever made twice, nothing is overwritten).

export const SCHED_SCHEMA = [
  `CREATE TABLE IF NOT EXISTS sjobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
     cls INTEGER NOT NULL DEFAULT 2, deadline REAL, est_min REAL NOT NULL DEFAULT 10, requires TEXT NOT NULL DEFAULT '[]',
     prefer TEXT NOT NULL DEFAULT '[]', fallback TEXT NOT NULL DEFAULT '[]', state TEXT NOT NULL DEFAULT 'queued',
     attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 5, run_after REAL NOT NULL DEFAULT 0,
     owner TEXT, last_owner TEXT, epoch INTEGER NOT NULL DEFAULT 0, until REAL, payload TEXT, result TEXT, error TEXT,
     created REAL NOT NULL, updated REAL NOT NULL)`,
  `CREATE INDEX IF NOT EXISTS sjobs_pick ON sjobs(state, cls, deadline)`,
  `CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, kind TEXT NOT NULL, caps TEXT NOT NULL DEFAULT '[]',
     slots TEXT NOT NULL DEFAULT '{}', version TEXT, load REAL, state TEXT NOT NULL DEFAULT 'active', seen REAL NOT NULL,
     first_seen REAL NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS presence (worker TEXT NOT NULL, hour INTEGER NOT NULL, PRIMARY KEY (worker, hour))`,
];

export const ONLINE_S = 120;              // seen within 2 minutes = online (heartbeat every 60 s)
export const LEASE_S = 900;               // 15 minutes; heartbeats extend it
export const WORKER_KINDS = ["pc", "gh_tick", "gh_render", "cf_worker"];
export const FAIL_KINDS = ["transient", "permanent", "quota"];
const DEFAULT_SLOTS = { 0: 2, 1: 1, 2: 1, 3: 1, 4: 1 };
const BACKOFF_BASE_S = 60, BACKOFF_CAP_S = 3600;

const J = (s, d) => { try { return JSON.parse(s); } catch (e) { return d; } };

export function makeScheduler(q, run, clock = () => Date.now() / 1000, rng = Math.random) {
  function worker(id) {
    const w = q(`SELECT * FROM workers WHERE id = ?`, id)[0];
    if (!w) return null;
    return { ...w, caps: J(w.caps, []), slots: { ...DEFAULT_SLOTS, ...J(w.slots, {}) } };
  }

  function online(now = clock(), kind = null) {
    return q(`SELECT id, kind FROM workers WHERE seen >= ? AND state = 'active'`, now - ONLINE_S)
      .filter(w => !kind || w.kind === kind);
  }

  // A fallback rule lets a non-preferred worker kind take the job when its condition holds.
  function fallbackOk(rule, slack, est_s, onlinePcs) {
    const conds = String(rule.when || "always").split("&");
    return conds.every(c => c === "always" || (c === "no_pc_online" && onlinePcs === 0) ||
                            (c === "slack_lt_2x" && slack < 2 * est_s));
  }

  return {
    register(w) {                          // {id, kind, caps, slots, version, load, state}
      if (!w || !w.id || !WORKER_KINDS.includes(w.kind)) throw new Error("bad worker");
      const now = clock();
      const st = ["active", "paused", "draining"].includes(w.state) ? w.state : null;   // null = keep the current one
      run(`INSERT INTO workers(id, kind, caps, slots, version, load, state, seen, first_seen)
           VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, 'active'), ?, ?)
           ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, caps = excluded.caps, slots = excluded.slots,
             version = excluded.version, load = excluded.load, seen = excluded.seen,
             state = COALESCE(?, workers.state)`,
          w.id, w.kind, JSON.stringify(w.caps || []), JSON.stringify(w.slots || {}), w.version || "",
          Number(w.load) || 0, st, now, now, st);
      run(`INSERT OR IGNORE INTO presence(worker, hour) VALUES (?, ?)`, w.id, Math.floor(now / 3600));
      return { ok: 1, online: online(now).length };
    },

    // Idempotent by key; a CANCELLED key opens again (23 Nov shadow check: the cloud cancels a job whenever its item
    // is not due for a while (claimed, pictures used up), and with INSERT OR IGNORE that key could never come back,
    // so the item would never have been handed out again once the scheduler was on). Leased, done and dead jobs
    // stay as they are; the epoch is never reset (fencing).
    enqueue(j) {
      if (!j || !j.kind || !j.key) throw new Error("bad job");
      const now = clock();
      const n = run(`INSERT INTO sjobs(kind, key, cls, deadline, est_min, requires, prefer, fallback, payload,
                       run_after, max_attempts, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                     ON CONFLICT(key) DO UPDATE SET state = 'queued', cls = excluded.cls, deadline = excluded.deadline,
                       est_min = excluded.est_min, requires = excluded.requires, prefer = excluded.prefer,
                       fallback = excluded.fallback, payload = excluded.payload, run_after = excluded.run_after,
                       updated = excluded.updated
                     WHERE sjobs.state = 'cancelled'`,
                    j.kind, j.key, Math.max(0, Math.min(4, Number(j.cls ?? 2))), j.deadline ?? null,
                    Number(j.est_min) || 10, JSON.stringify(j.requires || []), JSON.stringify(j.prefer || []),
                    JSON.stringify(j.fallback || []), JSON.stringify(j.payload || {}), Number(j.run_after) || 0,
                    Number(j.max_attempts) || 5, now, now);
      return { added: n === 1 };
    },

    claim(workerId, opts = {}) {
      const now = clock();
      const w = worker(workerId);
      if (!w || w.state !== "active") return { jobs: [], why: w ? `worker ${w.state}` : "unknown worker" };
      run(`UPDATE workers SET seen = ? WHERE id = ?`, now, workerId);
      run(`INSERT OR IGNORE INTO presence(worker, hour) VALUES (?, ?)`, workerId, Math.floor(now / 3600));
      run(`UPDATE sjobs SET state = 'queued', owner = NULL, until = NULL, updated = ?
           WHERE state = 'leased' AND until < ?`, now, now);              // crashed / asleep / switched-off workers
      const onlinePcs = online(now, "pc").filter(p => p.id !== workerId).length;
      const busy = {};
      for (const r of q(`SELECT cls, count(*) AS n FROM sjobs WHERE state = 'leased' AND owner = ? GROUP BY cls`, workerId))
        busy[r.cls] = r.n;
      const cands = q(`SELECT * FROM sjobs WHERE state = 'queued' AND run_after <= ? ORDER BY cls, deadline, id LIMIT 300`,
                      now);
      const allowed = [];
      for (const j of cands) {
        const requires = J(j.requires, []), prefer = J(j.prefer, []), fallback = J(j.fallback, []);
        if (!requires.every(c => w.caps.includes(c))) continue;
        const est_s = (Number(j.est_min) || 10) * 60;
        const slack = j.deadline == null ? Infinity : j.deadline - now - est_s;
        const ok = prefer.length === 0 || prefer.includes(w.kind) ||
                   fallback.some(f => f.kind === w.kind && fallbackOk(f, slack, est_s, onlinePcs));
        if (ok) allowed.push({ j, slack });
      }
      allowed.sort((a, b) => a.j.cls - b.j.cls || a.slack - b.slack || a.j.created - b.j.created || a.j.id - b.j.id);
      const limit = opts.limit === 0 ? 0 : Math.max(1, Number(opts.limit) || 1);   // 0 = housekeeping only
      const lease = Number(opts.lease_s) || LEASE_S;
      const out = [];
      for (const { j } of allowed) {
        if (out.length >= limit) break;
        const free = (w.slots[j.cls] ?? 1) - (busy[j.cls] || 0);
        if (free <= 0) continue;                                              // bulkhead: P2 never fills P0's slot
        if (run(`UPDATE sjobs SET state = 'leased', owner = ?, last_owner = ?, epoch = epoch + 1, until = ?,
                 attempts = attempts + 1, updated = ? WHERE id = ? AND state = 'queued'`,
                workerId, workerId, now + lease, now, j.id) !== 1) continue;
        busy[j.cls] = (busy[j.cls] || 0) + 1;
        const r = q(`SELECT * FROM sjobs WHERE id = ?`, j.id)[0];
        out.push({ id: r.id, kind: r.kind, key: r.key, cls: r.cls, deadline: r.deadline, epoch: r.epoch,
                   until: r.until, payload: J(r.payload, {}) });
      }
      return { jobs: out };
    },

    heartbeat(jobId, workerId, epoch, lease_s = LEASE_S) {
      const now = clock();
      run(`UPDATE workers SET seen = ? WHERE id = ?`, now, workerId);
      return { ok: run(`UPDATE sjobs SET until = ?, updated = ? WHERE id = ? AND owner = ? AND epoch = ? AND state = 'leased'`,
                       now + lease_s, now, jobId, workerId, epoch) === 1 };
    },

    // Accepted when the epoch is still current: leased to this worker, or its lease ran out and nobody took it over
    // (the work is done and no one else is making it). A late result after a re-lease (epoch moved on) is refused.
    complete(jobId, workerId, epoch, result = {}) {
      const now = clock();
      const n = run(`UPDATE sjobs SET state = 'done', result = ?, owner = NULL, until = NULL, updated = ?
                     WHERE id = ? AND epoch = ? AND epoch > 0 AND last_owner = ? AND state IN ('leased', 'queued')
                       AND (owner IS NULL OR owner = ?)`,
                    JSON.stringify(result || {}), now, jobId, epoch, workerId, workerId);
      return { ok: n === 1 };
    },

    fail(jobId, workerId, epoch, error = "", kind = "transient", retry_at = null) {
      if (!FAIL_KINDS.includes(kind)) throw new Error("bad fail kind");
      const now = clock();
      const j = q(`SELECT * FROM sjobs WHERE id = ? AND epoch = ? AND state = 'leased' AND owner = ?`,
                  jobId, epoch, workerId)[0];
      if (!j) return { state: "lost" };
      const attempts = j.attempts - (kind === "quota" ? 1 : 0);               // waiting for a quota is no failure
      let state = "queued", after = now + Math.max(30, rng() * Math.min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** Math.max(0, attempts - 1)));
      if (kind === "permanent" || attempts >= j.max_attempts) { state = "dead"; after = j.run_after; }
      else if (kind === "quota" && retry_at) after = Number(retry_at);
      run(`UPDATE sjobs SET state = ?, attempts = ?, run_after = ?, error = ?, owner = NULL, until = NULL, updated = ?
           WHERE id = ?`, state, attempts, after, String(error).slice(0, 1000), now, jobId);
      return { state };
    },

    cancel(key) {                          // no longer needed (made another way, slot dropped): queued jobs only
      const now = clock();
      return { ok: run(`UPDATE sjobs SET state = 'cancelled', updated = ? WHERE key = ? AND state = 'queued'`,
                       now, key) === 1 };
    },

    list(state = "queued", limit = 500) {
      return { jobs: q(`SELECT id, kind, key, cls, deadline, state, epoch, owner, attempts FROM sjobs WHERE state = ?
                        ORDER BY cls, deadline, id LIMIT ?`, String(state), Math.min(Number(limit) || 500, 2000)) };
    },

    release(workerId) {                    // clean shutdown: the jobs go back at once (epoch moves on at next claim)
      const now = clock();
      const n = run(`UPDATE sjobs SET state = 'queued', owner = NULL, until = NULL, updated = ?
                     WHERE owner = ? AND state = 'leased'`, now, workerId);
      run(`UPDATE workers SET seen = 0 WHERE id = ?`, workerId);
      return { released: n };
    },

    stats() {
      const now = clock();
      const by = {};
      for (const r of q(`SELECT state, cls, count(*) AS n FROM sjobs GROUP BY state, cls`)) by[`${r.state}:P${r.cls}`] = r.n;
      return { jobs: by, online: online(now) };
    },
  };
}
