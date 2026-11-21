// Phase 2 acceptance for cloud/worker/scheduler.js, on Node's built-in SQLite (the same code the LedgerDO runs).
// Run: node cloud/worker/scheduler.test.mjs   (exit 0 = pass; tests/test_scheduler_js.py runs it in the suite)
import { DatabaseSync } from "node:sqlite";
import { SCHED_SCHEMA, makeScheduler, LEASE_S } from "./scheduler.js";

function fresh(start = 1_800_000_000) {
  const db = new DatabaseSync(":memory:");
  for (const s of SCHED_SCHEMA) db.exec(s);
  const clock = { t: start };
  let seed = 12345;
  const rng = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const q = (s, ...a) => db.prepare(s).all(...a);
  const run = (s, ...a) => Number(db.prepare(s).run(...a).changes);
  return { s: makeScheduler(q, run, () => clock.t, rng), clock, q };
}
let failures = 0;
function check(name, cond) { if (!cond) { failures++; console.log("FAIL:", name); } }

const PC = { kind: "pc", caps: ["ffmpeg", "kokoro", "pc"] };
const GH = { kind: "gh_render", caps: ["ffmpeg", "kokoro"] };
const short = (key, deadlineIn, cls = 1, now) => ({ kind: "make", key, cls, deadline: now + deadlineIn, est_min: 10,
  requires: ["ffmpeg"], prefer: ["pc"], fallback: [{ kind: "gh_render", when: "no_pc_online&slack_lt_2x" }] });

// 1. A PC goes off mid-render: the job is re-leased after expiry, the late completion is refused by its epoch.
{
  const { s, clock } = fresh();
  s.register({ id: "pc1", ...PC }); s.register({ id: "pc2", ...PC });
  s.enqueue(short("a", 3 * 3600, 1, clock.t));
  const j = s.claim("pc1").jobs[0];
  check("pc1 got the job", j && j.epoch === 1);
  clock.t += LEASE_S + 5;                                   // pc1 sleeps: no heartbeat
  s.register({ id: "pc2", ...PC });
  const j2 = s.claim("pc2").jobs[0];
  check("re-leased to pc2 with a new epoch", j2 && j2.id === j.id && j2.epoch === 2);
  check("late pc1 completion refused", s.complete(j.id, "pc1", j.epoch, { file: "old" }).ok === false);
  check("late pc1 heartbeat refused", s.heartbeat(j.id, "pc1", j.epoch).ok === false);
  check("pc2 completes", s.complete(j2.id, "pc2", j2.epoch, { file: "new" }).ok === true);
  check("no second completion", s.complete(j2.id, "pc2", j2.epoch).ok === false);
}

// 2. Lease ran out but nobody took the job over: the original worker's result is still accepted.
{
  const { s, clock } = fresh();
  s.register({ id: "pc1", ...PC });
  s.enqueue(short("b", 9 * 3600, 2, clock.t));
  const j = s.claim("pc1").jobs[0];
  clock.t += LEASE_S + 60;
  s.claim("pc1", { limit: 0 });                             // any claim expires stale leases
  check("unclaimed expired job completes", s.complete(j.id, "pc1", j.epoch).ok === true);
}

// 3. P0 never waits behind P2: class order + per-class slots (bulkheads).
{
  const { s, clock } = fresh();
  s.register({ id: "pc1", ...PC, slots: { 0: 1, 2: 1 } });
  s.enqueue({ ...short("buffer", 60 * 3600, 2, clock.t) });
  const a = s.claim("pc1").jobs[0];
  check("P2 taken first when alone", a && a.cls === 2);
  s.enqueue({ kind: "post", key: "tap", cls: 0, deadline: clock.t + 300, est_min: 1, prefer: ["pc"] });
  const b = s.claim("pc1").jobs[0];
  check("P0 still gets its own slot while P2 runs", b && b.cls === 0);
  s.enqueue({ ...short("buffer2", 50 * 3600, 2, clock.t) });
  check("second P2 waits for the P2 slot", s.claim("pc1").jobs.length === 0);
}

// 4. EDF inside a class: the nearer deadline first.
{
  const { s, clock } = fresh();
  s.register({ id: "pc1", ...PC });
  s.enqueue(short("late", 20 * 3600, 1, clock.t));
  s.enqueue(short("soon", 2 * 3600, 1, clock.t));
  check("earliest deadline first", s.claim("pc1").jobs[0].key === "soon");
}

// 5. GitHub render only as a fallback: no PC online AND slack < 2x the estimate; long videos never.
{
  const { s, clock } = fresh();
  s.register({ id: "pc1", ...PC }); s.register({ id: "gh", ...GH });
  s.enqueue(short("tight", 25 * 60, 1, clock.t));          // slack 15 min < 2 x 10 min
  check("PC online: GH may not take it", s.claim("gh").jobs.length === 0);
  clock.t += 200;                                           // the PC goes quiet (> 120 s)
  s.register({ id: "gh", ...GH });
  const g = s.claim("gh").jobs[0];
  check("no PC + tight slack: GH takes it", g && g.key === "tight");
  s.enqueue(short("roomy", 10 * 3600, 1, clock.t));
  check("roomy slack: GH waits for the PC", s.claim("gh").jobs.length === 0);
  s.enqueue({ kind: "make", key: "long", cls: 1, deadline: clock.t + 600, est_min: 45, requires: ["pc"], prefer: ["pc"] });
  check("long video never sent to Actions", !s.claim("gh", { limit: 5 }).jobs.some(j => j.key === "long"));
}

// 6. Clean shutdown releases at once; paused workers get nothing; failures back off, permanent = dead.
{
  const { s, clock } = fresh();
  s.register({ id: "pc1", ...PC }); s.register({ id: "pc2", ...PC });
  s.enqueue(short("c", 5 * 3600, 1, clock.t));
  const j = s.claim("pc1").jobs[0];
  check("release returns the job", s.release("pc1").released === 1);
  const k = s.claim("pc2").jobs[0];
  check("pc2 takes it right away", k?.id === j.id);
  s.register({ id: "pc3", ...PC, state: "paused" });
  s.enqueue(short("d", 5 * 3600, 1, clock.t));
  check("paused worker gets nothing", s.claim("pc3").jobs.length === 0);
  s.register({ id: "pc3", ...PC });                          // state omitted: stays paused
  check("re-register keeps the pause", s.claim("pc3").jobs.length === 0);
  check("a full P1 slot takes no second P1 job", s.claim("pc2").jobs.length === 0);
  check("transient failure requeues", s.fail(k.id, "pc2", k.epoch, "net", "transient").state === "queued");
  clock.t += 3601;
  const k2 = s.claim("pc2").jobs.find(x => x.id === k.id);
  check("permanent failure is dead", k2 && s.fail(k2.id, "pc2", k2.epoch, "bad", "permanent").state === "dead");
  check("stale fail is lost", s.fail(k.id, "pc2", k.epoch, "x").state === "lost");
}

// 7. Property test: 10,000 randomized runs, never two accepted completions of one job.
{
  let seed = 987654321;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  let doubles = 0, completed = 0;
  for (let runNo = 0; runNo < 10000; runNo++) {
    const { s, clock } = fresh(1_800_000_000 + runNo);
    const ids = ["pc1", "pc2", "gh"];
    s.register({ id: "pc1", ...PC }); s.register({ id: "pc2", ...PC }); s.register({ id: "gh", ...GH });
    const held = [];                                        // leases workers believe they have (maybe stale)
    const done = {};
    for (let k = 0; k < 4; k++) s.enqueue(short(`j${k}`, (0.3 + rnd() * 6) * 3600, 1 + Math.floor(rnd() * 2), clock.t));
    for (let step = 0; step < 30; step++) {
      const r = rnd();
      const w = ids[Math.floor(rnd() * 3)];
      if (r < 0.3) { s.register({ id: w, ...(w === "gh" ? GH : PC) }); for (const j of s.claim(w).jobs) held.push({ ...j, w }); }
      else if (r < 0.55 && held.length) {
        const h = held.splice(Math.floor(rnd() * held.length), 1)[0];
        if (s.complete(h.id, h.w, h.epoch).ok) { done[h.id] = (done[h.id] || 0) + 1; completed++; }
      } else if (r < 0.65 && held.length) { const h = held[Math.floor(rnd() * held.length)]; s.heartbeat(h.id, h.w, h.epoch); }
      else if (r < 0.72 && held.length) { const h = held.splice(Math.floor(rnd() * held.length), 1)[0]; s.fail(h.id, h.w, h.epoch, "x"); }
      else if (r < 0.76) { s.release(w); }
      else clock.t += rnd() < 0.3 ? LEASE_S + 30 : rnd() * 300;
    }
    for (const n of Object.values(done)) if (n > 1) doubles++;
  }
  check(`zero double completions over 10,000 runs (completed ${completed})`, doubles === 0 && completed > 1000);
  console.log(`property: ${completed} completions, ${doubles} doubles`);
}

console.log(failures ? `${failures} check(s) failed` : "scheduler: all checks passed");
process.exit(failures ? 1 : 0);
