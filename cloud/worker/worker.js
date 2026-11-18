// HookHouse Telegram front door on Cloudflare Workers (free plan, no card).
// - Telegram sends every message/tap here (webhook). Only the owner's chat is accepted.
// - /status and /help are answered at once from the snapshot the cloud writes after each run.
// - Everything else is stored in KV (upd:<id>) and a GitHub run is started (at most every 10 minutes),
//   which handles it with the same Python code the PC bot used and replies on Telegram.
// - A cron every 15 minutes starts the scheduled runs at Indian times (GitHub's own timer can be late).
// Secrets (wrangler secret put): TG_TOKEN, TG_SECRET, OWNER_CHAT, GH_TOKEN. Vars: GH_REPO, TICK_SLOTS, RENDER_SLOT.

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

async function dispatch(env, eventType) {
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
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
      // the videos themselves need a cloud run; say at once how many and that they are coming
      const snap = JSON.parse((await env.HH.get("snapshot")) || "{}");
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
