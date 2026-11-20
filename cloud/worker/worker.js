// HookHouse Telegram front door on Cloudflare Workers (free plan, no card).
// - Telegram sends every message/tap here (webhook). Only the owner's chat is accepted.
// - /status and /help are answered at once from the snapshot the cloud writes after each run.
// - Everything else is stored in KV (upd:<id>) and a GitHub run is started (at most every 10 minutes),
//   which handles it with the same Python code the PC bot used and replies on Telegram.
// - A cron every 15 minutes starts the scheduled runs at Indian times (GitHub's own timer can be late).
// Secrets (wrangler secret put): TG_TOKEN, TG_SECRET, OWNER_CHAT, GH_TOKEN. Vars: GH_REPO, TICK_SLOTS, RENDER_SLOT.

import { LedgerDO, api } from "./ledger_do.js";   // Phase 1 (20 Nov): shared truth, /api/* signed with HH_API_KEY
export { LedgerDO };

const IST_OFFSET_MIN = 330;
const DEBOUNCE_MS = 2 * 60 * 1000;     // 18 Nov: 10 min made the bot look dead ("telegram is not working")

// Info buttons answered at once from the texts the cloud keeps after every run (snapshot.texts).
const INSTANT = [
  [/^\/(tasks|task|todo_all)\b/, "📋 My tasks", "tasks"],
  [/^\/health\b/, "🛠️ Anything broken?", "health"],
  [/^\/channels\b/, "📈 Numbers", "channels"],
  [/^\/heal\b/, null, "heal"],
  [/^\/review\s*$/, null, "review"],
  [/^\/books\s*$/, null, "books"],
];

async function tg(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
}

async function pcPrimary(env) {
  // 18 Nov (GitHub suspended): the PC stands in (engine/pc_fallback.py). While its heartbeat is fresh, no cloud
  // runs are started: the PC reads the inbox (upd:*) and the dashboard taps (cmd:*) itself.
  // The flag stays until the PC hands over (it pushes its memory first), even if the PC is off for a while: the
  // cloud must not resume from its older memory and post twice. After 24 h without a heartbeat the cloud resumes.
  const pc = JSON.parse((await env.HH.get("meta:pc_primary")) || "null");
  if (!pc) return false;
  const age = Date.now() / 1000 - pc.at;
  if (age > 900 && age < 86400) {                 // the PC is off (heartbeat every 5 min): tell the owner (at most every 3 hours)
    const last = Number((await env.HH.get("meta:pc_off_warn")) || 0);
    if (Date.now() - last > 3 * 3600 * 1000) {
      await env.HH.put("meta:pc_off_warn", String(Date.now()));
      await tg(env, "sendMessage", { chat_id: env.OWNER_CHAT, text:
        "💻 The PC stand-in is off, so taps and posts wait. Please switch the PC on (it starts by itself) until " +
        "GitHub restores the cloud." });
    }
  }
  return age < 86400;
}

async function dispatch(env, eventType) {
  if (await pcPrimary(env)) return false;
  const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json",
      "user-agent": "hookhouse-worker", "content-type": "application/json",
    },
    body: JSON.stringify({ event_type: eventType }),
  });
  if (r.status === 204) {
    await env.HH.delete("meta:dispatch_fail");
    return true;
  }
  // 17 Nov: a redeploy lost GH_REPO and every run start failed silently for hours. Never silent again:
  // tell the owner (at most once an hour) what failed.
  const lastWarn = Number((await env.HH.get("meta:dispatch_fail")) || 0);
  if (Date.now() - lastWarn > 3600 * 1000) {
    await env.HH.put("meta:dispatch_fail", String(Date.now()));
    await tg(env, "sendMessage", { chat_id: env.OWNER_CHAT, text:
      `⚠️ HookHouse alarm: the cloud run "${eventType}" could not start (GitHub said ${r.status}, repo "${env.GH_REPO}"). ` +
      "Your taps are saved and will run once this is fixed. Tell Claude: 'worker dispatch failing'." });
  }
  return false;
}

async function wakeInbox(env, force = false) {
  const last = Number((await env.HH.get("meta:last_dispatch")) || 0);
  if (!force && Date.now() - last < DEBOUNCE_MS) return false;
  if (await dispatch(env, "inbox")) {
    await env.HH.put("meta:last_dispatch", String(Date.now()));
    return true;
  }
  return false;
}

function istNow() {
  const d = new Date(Date.now() + IST_OFFSET_MIN * 60000);
  return { hhmm: d.toISOString().slice(11, 16), day: d.toISOString().slice(0, 10), mins: d.getUTCHours() * 60 + d.getUTCMinutes() };
}

function minsOf(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

// Campaign digest keyboard: number buttons "⬜ 3"/"☑️ 3" (t:2), then a row with "✅ Confirm N picked" (c).
// "a" ticks every line the digest marked ready ("3. ✅ ...").
function pickKeyboard(rows, data, text) {
  const ready = new Set([...text.matchAll(/^(\d+)\. ✅/gm)].map(m => Number(m[1]) - 1));
  const out = rows.map(r => r.map(b => ({ ...b })));
  let n = 0;
  for (const r of out) for (const b of r) {
    const m = /^t:(\d+)$/.exec(b.callback_data || "");
    if (!m) continue;
    const i = Number(m[1]);
    let on = b.text.startsWith("☑️");
    if (data === "a") on = ready.has(i) || on;
    else if (data === `t:${i}`) on = !on;
    b.text = (on ? "☑️ " : "⬜ ") + (i + 1);
    if (on) n++;
  }
  for (const r of out) for (const b of r) if (b.callback_data === "c") b.text = `✅ Confirm ${n} picked`;
  return out;
}

// Same six bottom buttons as engine/telegram_bot.py MENU (owner 17 Nov: "make telegram easily understandable").
const MENU_KB = { keyboard: [[{ text: "📋 My tasks" }, { text: "📥 Waiting for me" }],
                             [{ text: "📊 Today" }, { text: "💰 Campaigns" }],
                             [{ text: "📈 Numbers" }, { text: "🛠️ Anything broken?" }],
                             [{ text: "❓ Help" }]],
                  resize_keyboard: true, is_persistent: true };
const HELP = "👋 HookHouse, in short\n\n" +
  "Fastest: tap 🎬 Studio (left of the message box) to watch, approve, change or reject every video in one place.\n\n" +
  "Use the buttons at the bottom:\n" +
  "📋 My tasks: what is left for you, and what is approved and coming\n" +
  "📥 Waiting for me: videos and books that need your OK\n" +
  "📊 Today: what was made, posted and planned today\n" +
  "💰 Campaigns: pick paid clipping campaigns\n" +
  "📈 Numbers: views and subscribers per channel\n" +
  "🛠️ Anything broken?: a live check of the whole system\n\n" +
  "On every video: ✅ Approve · ✏️ Change (then type what to fix) · ❌ Reject. Nothing is posted without your ✅.\n\n" +
  "Campaigns in 3 steps: 1) tick the numbers you want  2) press Confirm  3) open each Join button I send and press " +
  "Join Campaign. I find the footage and make the clips by myself.\n\n" +
  "Buttons other than Today and Help answer within a few minutes. If something stops working, I tell you with ⚠️.";

// Signed, short-lived video links (17 Nov): Instagram API with Instagram/unified login only accepts a public video_url
// (direct file upload is for Facebook-Login Page tokens). /v/<asset id>/<expiry unix s>/<hex HMAC-SHA256> streams one
// file of the private "share" release; the HMAC key is "media:" + TG_SECRET, so only our own runs can make links.
async function hmacHex(key, msg) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function media(request, env, url) {
  const [, , asset, exp, sig] = url.pathname.split("/");
  if (!/^\d+$/.test(asset || "") || !/^\d+$/.test(exp || "") || Number(exp) < Date.now() / 1000) return new Response("gone", { status: 410 });
  const want = await hmacHex("media:" + env.TG_SECRET, `${asset}.${exp}`);
  if (!sig || sig.length !== want.length || sig !== want) return new Response("no", { status: 403 });
  const gh = await fetch(`https://api.github.com/repos/${env.STORE_REPO || env.GH_REPO}/releases/assets/${asset}`, {
    headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/octet-stream", "user-agent": "hookhouse-bot" },
    redirect: "manual" });
  const loc = gh.headers.get("location");
  if (!loc) return new Response("not found", { status: 404 });
  const range = request.headers.get("range");     // the signed storage link must NOT get our GitHub key
  const r = await fetch(loc, { headers: range ? { range } : {} });
  if (!r.ok && r.status !== 206) return new Response("not found", { status: 404 });
  const out = new Headers({ "content-type": "video/mp4", "accept-ranges": "bytes", "cache-control": "no-store" });
  for (const h of ["content-length", "content-range"]) if (r.headers.get(h)) out.set(h, r.headers.get(h));
  return new Response(request.method === "HEAD" ? null : r.body, { status: r.status, headers: out });
}

// Owner's live dashboard (phone or PC): /d?k=DASH_KEY serves the page the PC/cloud built (KV dash:html);
// /cmd stores a button tap (cmd:<id>) for the PC/cloud; /res shows its outcome (res:<id>).
const DASH_OPS = ["approve", "upload", "change", "reject", "make", "refresh"];
function dashOk(env, url) {
  const k = url.searchParams.get("k") || "";
  return Boolean(env.DASH_KEY && env.DASH_KEY.length >= 16 && k.length === env.DASH_KEY.length && k === env.DASH_KEY);
}
// Live numbers on every page load (owner 18 Nov: "page load gets all the live data"): YouTube public counters for
// every channel and posted video, fetched here (no PC needed). Kept 90 s in this isolate's memory, so page views
// cost no KV writes (free plan: 1,000 writes/day) and little YouTube quota (~3 units per refresh).
let LIVE = { at: 0, data: null };
let LISTS = { at: 0, data: {} };                   // cid -> latest upload ids (10 min: 1 unit per channel)
async function yt(env, path) {
  const r = await fetch(`https://www.googleapis.com/youtube/v3/${path}&key=${env.YT_KEY}`);
  if (!r.ok) throw new Error(`YouTube ${path.split("?")[0]} ${r.status}`);
  return (await r.json()).items || [];
}
async function liveNumbers(env) {
  const now = Date.now() / 1000;
  if (LIVE.data && now - LIVE.at < 90) return LIVE.data;
  const ids = JSON.parse((await env.HH.get("dash:ids")) || "{}");
  const data = { at: now, built: ids.built || 0, meta: ids.meta || {}, channels: {}, videos: {}, error: null };
  try {
    if (!env.YT_KEY) throw new Error("no YouTube key on the Worker");
    const chans = ids.channels || {};                      // cid -> YouTube channel id
    const byYt = Object.fromEntries(Object.entries(chans).map(([c, y]) => [y, c]));
    const ups = {};
    const list = Object.values(chans);
    for (let i = 0; i < list.length; i += 50) {
      for (const it of await yt(env, `channels?part=statistics,contentDetails&id=${list.slice(i, i + 50).join(",")}`)) {
        const st = it.statistics || {}, cid = byYt[it.id];
        data.channels[cid] = { subs: Number(st.subscriberCount || 0), views: Number(st.viewCount || 0),
                               videos: Number(st.videoCount || 0), latest: [] };
        ups[cid] = ((it.contentDetails || {}).relatedPlaylists || {}).uploads;
      }
    }
    if (now - LISTS.at > 600) {
      const fresh = {};
      for (const [cid, pl] of Object.entries(ups)) {
        if (!pl) continue;
        try { fresh[cid] = (await yt(env, `playlistItems?part=contentDetails&maxResults=10&playlistId=${pl}`))
                .map(x => x.contentDetails.videoId); } catch (e) { fresh[cid] = LISTS.data[cid] || []; }
      }
      LISTS = { at: now, data: fresh };
    }
    const want = new Set(Object.keys(ids.videos || {}));
    for (const v of Object.values(LISTS.data).flat()) want.add(v);
    const all = [...want];
    for (let i = 0; i < all.length; i += 50) {
      for (const it of await yt(env, `videos?part=statistics,snippet&id=${all.slice(i, i + 50).join(",")}`)) {
        const st = it.statistics || {}, sn = it.snippet || {};
        data.videos[it.id] = { views: Number(st.viewCount || 0), likes: Number(st.likeCount || 0),
          comments: Number(st.commentCount || 0), title: sn.title || "", at: sn.publishedAt || "",
          thumb: ((sn.thumbnails || {}).medium || (sn.thumbnails || {}).default || {}).url || "" };
      }
    }
    for (const [cid, vids] of Object.entries(LISTS.data)) {
      if (data.channels[cid]) data.channels[cid].latest = vids.filter(v => data.videos[v]);
    }
  } catch (e) {
    data.error = String(e.message || e);
  }
  LIVE = { at: now, data };
  return data;
}

const SEC = { "cache-control": "no-store", "x-robots-tag": "noindex", "referrer-policy": "no-referrer" };
// Review player (owner 19 Nov: "a video player to review the videos"): the PC puts a light copy of every video waiting
// for the owner in KV as 20 MB pieces (pv:<item>:meta, pv:<item>:<n>). Byte ranges, so phones (iPhone needs them)
// can play and seek.
async function preview(request, env, url) {
  const id = (url.searchParams.get("id") || "").replace(/[^0-9A-Za-z_-]/g, "");
  const meta = id ? JSON.parse((await env.HH.get(`pv:${id}:meta`)) || "null") : null;
  if (!meta) return new Response("This video's preview isn't ready yet.", { status: 404, headers: SEC });
  const size = meta.size, chunk = meta.chunk;
  let start = 0, end = size - 1, partial = false;
  const m = /bytes=(\d*)-(\d*)/.exec(request.headers.get("range") || "");
  if (m) {
    partial = true;
    if (m[1] === "") { start = Math.max(0, size - Number(m[2] || 0)); }
    else { start = Number(m[1]); if (m[2] !== "") end = Math.min(size - 1, Number(m[2])); }
    if (start >= size || start > end) return new Response(null, { status: 416, headers: { "content-range": `bytes */${size}` } });
  }
  end = Math.min(end, start + chunk - 1, (Math.floor(start / chunk) + 1) * chunk - 1);   // one piece per answer
  const n = Math.floor(start / chunk);
  const h = { "content-type": "video/mp4", "accept-ranges": "bytes", "content-length": String(end - start + 1), ...SEC };
  if (partial || end < size - 1) h["content-range"] = `bytes ${start}-${end}/${size}`;
  if (request.method === "HEAD") return new Response(null, { status: partial ? 206 : 200, headers: h });
  const buf = await env.HH.get(`pv:${id}:${n}`, { type: "arrayBuffer" });
  if (!buf) return new Response("gone", { status: 404, headers: SEC });
  const off = start - n * chunk;
  return new Response(buf.slice(off, off + (end - start + 1)), { status: (partial || end < size - 1) ? 206 : 200, headers: h });
}
async function dash(request, env, url) {
  if (!dashOk(env, url)) return new Response("no", { status: 403 });
  if (url.pathname === "/d") {
    const page = await env.HH.get("dash:html");
    return new Response(page || "<p>The dashboard is being built. Try again in a few minutes.</p>",
      { headers: { "content-type": "text/html; charset=utf-8", ...SEC } });
  }
  if (url.pathname === "/live") return Response.json(await liveNumbers(env), { headers: SEC });
  if (url.pathname === "/res") {
    const id = (url.searchParams.get("id") || "").replace(/[^0-9a-z-]/gi, "");
    const r = id ? await env.HH.get(`res:${id}`) : null;
    return new Response(r || JSON.stringify({ state: "queued" }), { headers: { "content-type": "application/json", ...SEC } });
  }
  if (url.pathname === "/pv") return preview(request, env, url);
  if (url.pathname === "/cmd" && request.method === "POST") {
    let b = {};
    try { b = await request.json(); } catch (e) { b = {}; }
    if (!DASH_OPS.includes(b.op)) return Response.json({ error: "unknown button" }, { status: 400 });
    const cmd = { op: b.op, item: String(b.item || "").slice(0, 80), note: String(b.note || "").slice(0, 500),
                  force: Boolean(b.force), at: Date.now() / 1000 };
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    await env.HH.put(`cmd:${id}`, JSON.stringify(cmd), { expirationTtl: 2 * 86400 });
    await env.HH.put(`res:${id}`, JSON.stringify({ state: "queued" }), { expirationTtl: 2 * 86400 });
    const pc = await pcPrimary(env);
    if (!pc) await dispatch(env, "inbox");       // the cloud handles taps too (runner reads cmd:* once it is back)
    return Response.json({ id, pc }, { headers: SEC });
  }
  return new Response("no", { status: 404 });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (["/d", "/cmd", "/res", "/live", "/pv"].includes(url.pathname)) return dash(request, env, url);
    if (url.pathname.startsWith("/api/")) return env.LEDGER ? api(request, env, url, hmacHex) : new Response("no", { status: 404 });
    if ((request.method === "GET" || request.method === "HEAD") && url.pathname.startsWith("/v/")) return media(request, env, url);
    if (request.method !== "POST" || url.pathname !== "/tg") return new Response("ok");
    if (request.headers.get("x-telegram-bot-api-secret-token") !== env.TG_SECRET) return new Response("no", { status: 401 });
    const update = await request.json();
    const msg = update.message || (update.callback_query && update.callback_query.message);
    const chat = String((msg && msg.chat && msg.chat.id) || "");
    if (chat !== String(env.OWNER_CHAT)) return new Response("ok");      // only the owner controls HookHouse

    const text = (update.message && update.message.text) || "";
    if (/^\/status\b/.test(text) || text === "📊 Today") {
      const snap = JSON.parse((await env.HH.get("snapshot")) || "{}");
      const age = snap.at ? Math.round((Date.now() / 1000 - snap.at) / 60) : null;
      await tg(env, "sendMessage", { chat_id: chat, text: (snap.status || "No status yet.") + (age !== null ? `\n\n(updated ${age} min ago)` : "") });
      return new Response("ok");
    }
    if (/^\/(help|start|menu)\b/.test(text) || text === "❓ Help") {
      await tg(env, "sendMessage", { chat_id: chat, text: HELP, reply_markup: MENU_KB });
      return new Response("ok");
    }
    for (const [rx, button, key] of INSTANT) {
      if (!(rx.test(text) || (button && text === button))) continue;
      const snap = JSON.parse((await env.HH.get("snapshot")) || "{}");
      const body = snap.texts && snap.texts[key];
      if (!body) break;                                  // not in the snapshot yet: a cloud run answers it
      const age = snap.at ? Math.round((Date.now() / 1000 - snap.at) / 60) : null;
      await tg(env, "sendMessage", { chat_id: chat, text: body + (age !== null ? `\n\n(updated ${age} min ago)` : "") });
      return new Response("ok");
    }
    if (/^\/queue\b/.test(text) || text === "📥 Waiting for me") {
      // 20 Nov (owner: "a button for waiting for approval that gives the list of videos that need my approval"):
      // the cards come from the snapshot at once; videos already decided since then are left out.
      const snap = JSON.parse((await env.HH.get("snapshot")) || "{}");
      const q = snap.queue;
      if (q && Array.isArray(q.cards)) {
        const open = [];
        for (const c of q.cards) if (!(await env.HH.get(`dec:${c.tok}`))) open.push(c);
        const decided = q.cards.length - open.length;
        let head = q.header;
        if (decided) head = open.length || q.checking ? `📥 ${open.length} video(s) still need your OK (you decided ${decided} already)` +
          (q.checking ? ` · ${q.checking} more being checked` : "") : "📥 All done: nothing is waiting for you. 👍";
        await tg(env, "sendMessage", { chat_id: chat, text: head, ...(open.length > 1 && q.header_kb ? { reply_markup: q.header_kb } : {}) });
        for (const c of open) await tg(env, "sendMessage", { chat_id: chat, text: c.text, reply_markup: c.reply_markup });
        return new Response("ok");
      }
      const n = snap.waiting;
      await tg(env, "sendMessage", { chat_id: chat, text: n === 0 ? "📥 Nothing is waiting for you right now. 👍" :
        `📥 ${n ?? "Your"} video(s) waiting. Sending them with ✅ / ✏️ / ❌ buttons in a few minutes…` });
      if (n !== 0) {
        await env.HH.put(`upd:${String(update.update_id).padStart(12, "0")}`, JSON.stringify(update), { expirationTtl: 7 * 86400 });
        await wakeInbox(env, true);
      }
      return new Response("ok");
    }
    const cq = update.callback_query;
    if (cq && /^(t:\d+|a)$/.test(cq.data || "") && cq.message && cq.message.reply_markup) {
      // campaign tick boxes: flip them here at once (a cloud run takes minutes, so taps looked dead)
      const kb = pickKeyboard(cq.message.reply_markup.inline_keyboard, cq.data, cq.message.text || "");
      await tg(env, "editMessageReplyMarkup", { chat_id: chat, message_id: cq.message.message_id, reply_markup: { inline_keyboard: kb } });
      await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: cq.data === "a" ? "Ticked all ✅ ones" : "" });
      return new Response("ok");
    }
    await env.HH.put(`upd:${String(update.update_id).padStart(12, "0")}`, JSON.stringify(update), { expirationTtl: 7 * 86400 });
    const dec = cq && /^(ap|rj|ch):([0-9a-f]{6,16})$/.exec(cq.data || "");
    if (dec) {
      // 20 Nov: the tap shows its result on the card at once (the cloud run does the work a moment later)
      const [, act, tok] = dec;
      await env.HH.put(`dec:${tok}`, act, { expirationTtl: 3 * 86400 });
      const label = { ap: "✅ Approved: posts at its slot", rj: "❌ Rejected", ch: "✏️ Change: type what to fix" }[act];
      await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: label });
      if (cq.message) await tg(env, "editMessageReplyMarkup", { chat_id: chat, message_id: cq.message.message_id,
        reply_markup: { inline_keyboard: [[{ text: label, callback_data: "noop" }]] } });
      if (act === "ch") await tg(env, "sendMessage", { chat_id: chat, reply_markup: { force_reply: true }, text:
        "✏️ What should I change? Type it in one message, for example: \"make the hook scarier\", \"use a different " +
        "first picture\". Only the title? Type \"title 2\" or \"title: your words\" (no remake needed)." });
      await wakeInbox(env, true);
      return new Response("ok");
    }
    if (cq && cq.data === "c") {
      await tg(env, "answerCallbackQuery", { callback_query_id: cq.id, text: "✅ Saved. Joining and fetching footage now…" });
      await wakeInbox(env, true);                    // the owner is waiting: no 10-minute debounce
      return new Response("ok");
    }
    if (update.callback_query) {
      await tg(env, "answerCallbackQuery", { callback_query_id: update.callback_query.id, text: "✅ Saved, doing it now" });
    } else {
      await tg(env, "sendMessage", { chat_id: chat, text: "⏳ Got it, working on it (a few minutes)…" });
    }
    await wakeInbox(env, Boolean(update.callback_query));   // a tap (approve / reject) starts a run at once
    return new Response("ok");
  },

  async scheduled(event, env) {
    // 1) messages waiting longer than the debounce: run now
    const pending = await env.HH.list({ prefix: "upd:", limit: 1 });
    if (pending.keys.length) await wakeInbox(env);
    // 2) the day's scheduled runs, at Indian times (each slot once a day)
    const now = istNow();
    const slots = (env.TICK_SLOTS || "06:00,10:00,14:00,18:00,22:30,01:30").split(",").map(s => s.trim());
    for (const s of slots) {
      const key = `meta:tick:${now.day}:${s}`;
      if (now.mins >= minsOf(s) && now.mins < minsOf(s) + 30 && !(await env.HH.get(key))) {
        if (await dispatch(env, "tick")) await env.HH.put(key, "1", { expirationTtl: 3 * 86400 });
      }
    }
    // 18 Nov: one render a day made ~3 videos for 14 channels; RENDER_SLOT may now list several times
    for (const r of (env.RENDER_SLOT || "20:00").split(",").map(s => s.trim())) {
      const rkey = `meta:render:${now.day}:${r}`;
      if (now.mins >= minsOf(r) && now.mins < minsOf(r) + 30 && !(await env.HH.get(rkey))) {
        if (await dispatch(env, "render")) await env.HH.put(rkey, "1", { expirationTtl: 3 * 86400 });
      }
    }
  },
};
