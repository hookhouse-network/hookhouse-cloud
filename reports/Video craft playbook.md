# Video craft playbook

*Clip Factory, 10 Nov 2026. This report pulls together the craft findings already gathered in Report 1's notes
(measured from top 2025–26 channels via preview frames and captions) with a few focused checks.
Section sources are the notes files in `research_notes/Viral faceless video formats 2026/`.
Labels: [M] = measured or sourced, [D] = our design default (to tune with our own analytics).*

## 0. Verified after the deep pass (10 Nov 2026, evening; research_notes/deep_pass_2026-11-10.md)
- **The hook is measurable on both platforms:**
  - YouTube Shorts: "viewed vs swiped away" (aim for 70–80%+).
  - Instagram: **skip rate**, the share of viewers who leave in the first 3 s.
  - → Our first-frame and first-line rules are the most important craft rules.
- **Upload settings confirmed (YouTube):** H.264 High, closed GOP, 1080p at 8 Mbps (30 fps) / 12 Mbps (60 fps). Ours meet or exceed this. "Upload in 4K to get VP9" is unproven, so we don't rely on it.
- **Instagram:**
  - Reels up to 20 min, but keep 15–90 s for reach.
  - **Max 5 hashtags.**
  - Trial Reels via the API to test hooks.
- **Shorts music** cuts a Short's revenue-pool share by half or more, so we keep our own collision notes and beds, with no licensed tracks on monetised Shorts.
- **Voices:** Chatterbox Multilingual (MIT) confirmed; a 2026 paper reports commercial-class Hindi intelligibility. Run a listening test against Indic Parler-TTS (check its gated licence first) and Kokoro.

## 1. Hooks (first 1–3 seconds)
- **The first frame is the hook visual.** No logo, title card, greeting or black frame [M, all niches].
- **First spoken line = the climax or the stakes, mid-scene** [M]:
  - Mystery: "He put his sons in the lifeboat, but instead of joining them…"
  - Sports: "India need 15 runs off 6 balls." The pattern is stakes plus an exact number.
  - Money: "This man paid $0 tax on $1 billion. Legally."
  - Facts: a shocking visual premise in 1–2 s (Zack D. Films).
- **On-screen hook text** (muted viewers) says the same thing within 0.5 s, max 6–8 words, top 15–27% of the frame, white box with black text [M/D].
- **Banned openers:** "Did you know", "In this video", "Imagine", "Hey guys", "Wait for it" without a payoff [M].
- **Title, thumbnail and first line deliver the same promise**, and the video pays it off. YouTube's Test & Compare picks winners by watch time, so misleading hooks lose [M].

## 2. Script structure
- **Shorts, story channels** (measured on mystery 3D micro-stories) [M]:
  1. Cold open (0–3 s): the climax or stakes.
  2. "You see," backstory (by 4–8 s): who, where, when.
  3. Escalation, with a new question, number or reveal every 6–10 s.
  4. "But…" twist at 40–60%.
  5. Ironic or surprising payoff. **No call to action.**
  6. Last line flows into the first line, so the Short loops.
- **Money/explainers:** one idea per Short. Numbers and proof on screen carry the meaning. Loop the ending [M].
- **Long-form (8–30 min):**
  - Chapter structure with a re-hook at each chapter.
  - Numbered series ("Pt. 2", "Vol. N") and compilations for watch time.
  - Shorts cut from the long video within 3 days of it going up [M, mystery and money notes].
- **Pace of words** [M]:
  - Mystery/documentary: 170–200 words per minute (about 150 words in a 50 s Short).
  - Cartoon/3D explainers: 120–150 wpm.
  - Hindi narration: a bit slower, with dramatic pauses before reveals [D].
- **Built into our writer prompt** (`engine/story.py`, 10 Nov 2026): cold open, backstory, twist, ironic payoff, loop, no CTA, at most 1 emoji, at most 2 text graphics.

## 3. Voiceover
- **Flat TTS is the "dated" signal that undoes any visual upgrade** [M].
- **Styles per channel:**
  - Mystery: deep, calm, slightly fast.
  - Sports: energetic, commentator-like (Hindi cricket: "kissa" storyteller tone).
  - Money: conversational and friendly.
  - Mythology: deep, slow, reverent male voice.
  - Brain Snack quiz: upbeat.
  - Kids: warm and slow, with a singer for songs [M/D].
- **Free options** (see `free_production_toolchain.md`): Kokoro now; test Chatterbox Multilingual (MIT, EN+HI, emotion control) on Colab and Indic Parler-TTS (Apache-2.0) for Hindi. Never F5-TTS base (non-commercial).
- **Processing** [D]: trim silences (done); keep pauses under 450 ms; light compression; −14 LUFS final loudness (done in clips and snack).
- **Disclosure:** use YouTube's altered/synthetic label only for realistic content. An AI voice reading our own script doesn't need it; YouTube says disclosure doesn't hurt reach [M]. India's IT Rules 2026 require labels on AI audio/video, so note "AI voice" in descriptions [M].

## 4. Music
- **Safe sources:**
  - our own procedural beds (built)
  - ACE-Step 1.5 (MIT per its model card, generated music usable commercially; check the repo licence before use)
  - YouTube Audio Library (no Content ID claims; manual download)
  - Mixkit (free for YouTube)
  - Never popular songs, and never Pixabay tracks without keeping the licence PDF [M].
- **Platform licensed sounds:** in-app trending audio on Reels and Shorts is licensed only inside the apps. It can't be added through API uploads, and on YouTube music reduces a Short's revenue share. Use it only for manual Instagram posts where trending audio matters [M/D].
- **Levels** [M/D]:
  - Music bed 20–24 dB under speech (about −32 to −36 LUFS), ducked under the voice.
  - None or very low for podcast clips (most campaigns ban added music).
  - Brain Snack: collision notes replace music entirely (built).
- **Per-channel identity:** each channel gets its own music mood and key (dark drone for mystery, epic for sports, light for money, tanpura/conch-drone for mythology). Never the same bed across channels (spam policy) [M].

## 5. Sound effects
- **Restraint is current:** at most one subtle impact per punch-in or reveal, a whoosh only on real section changes, risers before twists. No meme sounds or per-word SFX [M].
- **Sources:**
  - our own synthesised SFX (built: whoosh, impact, riser, tick, ding, gong, clack)
  - **Sonniss GDC bundles**: licence checked today: worldwide, royalty-free, commercial use, no attribution, any medium including videos; AI training banned; multi-GB downloads [V]
  - Mixkit SFX
  - Freesound CC0, by hand only (its API is non-commercial) [M].
- **Levels:** SFX about 15 dB under speech; transitions −20 dB [D].

## 6. Captions and text
- **Dated:**
  - Anton/Impact yellow all-caps karaoke
  - giant text slabs
  - rainbow colours per word
  - emoji on every line
  - bouncing pop-ins [M]
- **Current** [M]:
  - 1–3 words per chunk in sentence case, a heavy clean sans (Poppins/Montserrat ExtraBold)
  - white with 4 px outline and 2 px soft shadow
  - **one** accent colour on the spoken or key word
  - subtle 92→100% scale-in over 100 ms
- **Position** [M]:
  - About 60% height for clips (below the chin).
  - About 65% for story Shorts.
  - The split seam (50%) in split layouts.
  - Keep out of the top 14% and bottom 35% (Instagram safe zone), and leave a right margin for the Shorts buttons.
- **Size:** cap height about 62 px at 1080×1920 (Poppins ExtraBold fontsize about 118–124 in libass) [M/D].
- **Money channel:** no karaoke captions at all. Numbers, labels and proof screenshots carry the meaning [M].
- **Hindi:**
  - Devanagari with letter-spacing 0 (otherwise libass breaks the vowel signs).
  - Viral Hindi Shorts often caption in Roman-script Hinglish over Hindi narration, with Devanagari on thumbnails and punch cards. A/B test both [M].
  - Fonts (OFL): Mukta 800, Baloo 2, Yatra One/Rozha One titles, Teko/Rajdhani numbers, Noto Sans Devanagari fallback. Poppins also covers Devanagari [M].
- **Subtitle files:** upload SRT captions too (search, accessibility). Use YouTube's auto-translate and auto-dubbing for extra languages on long-form [K].
- **Status:** **BUILT** as `modern=True` captions (story) and clipv3 captions (clips).

## 7. Animation and motion graphics
- **What replaced Ken Burns, in order** [M]:
  1. AI video or 3D shots, cutting every 1–2 s.
  2. Documentary collage: article and newspaper highlight wipes, maps, evidence boards, counters.
  3. **2.5D depth parallax on stills** (BUILT).
  4. Stylised 3D/2D characters.
- **Graphics kit to build (shared, re-themed per channel):**
  - Newspaper headline: our own mock-up, never real logos.
  - Highlighter wipe: 40% yellow, left to right, 300 ms.
  - Evidence card: paper texture, slight tilt, tape.
  - Map pin: Natural Earth, public domain.
  - Counter: numbers roll up.
  - Scoreboard bar and "NEED X OFF Y" card (sports).
  - Quote card.
  - Chapter card (long-form).
- **Consistent characters:**
  - Brain Snack Squad roster (built).
  - A money mascot (to design).
  - Mythology deity designs fixed per deity, kept respectful.
  - Kids: Bloop.
  - Human-designed, so we can own them (AI-made characters get little copyright protection) [M].

## 8. Transitions and camera moves
- **Mostly hard cuts.** A visual change every 1.5–3 s in narrated Shorts, every 3–6 s in podcast clips [M].
- **Allowed:**
  - snap punch-ins (1.12–1.15×) on payoff words, held 3 s or more
  - slow parallax pushes
  - occasional whip or zoom transitions on section changes (at most 2 per video)
  - a white flash only on the one big reveal [M]
- **Banned (dated):**
  - constant shake
  - glitch/RGB split
  - star/cube/spin wipes
  - transitions on every cut [M]
- **Status:** **BUILT.** Story transition sets are now mostly cuts with no glitch; clips use snap punches only.

## 9. Editing pace and retention
- **Shorts length** [M]:
  - vidIQ: view peaks at about 13 s and about 60 s, average viewed 73.6%.
  - Footage-free story Shorts can run 60–180 s (no Content ID block).
  - Hot takes 18–30 s; stories 35–60 s.
- **Retention tricks that are current:**
  - a rehook every 6–10 s
  - an escalation beat at about 40%
  - abrupt endings with no outro
  - loops: the last line feeds the first [M]
- **Instagram Reels:** up to 3 min; profile-grid crop 3:4. Trial Reels for testing [M].
- **Measure:** YouTube "viewed vs swiped away", engaged views, average percentage viewed and loop rate; Instagram skip rate. See the analytics section in Report 3.

## 10. Color and video quality
- **Grade per channel:**
  - Mystery: teal/amber, crushed blacks, grain 6.
  - Sports: warm and punchy.
  - Money: clean and bright.
  - Mythology: warm gold, grain 7.
  - Brain Snack: neon on dark, or cream with black outlines.
  - Kids: soft-bright pastels.
  - (Built: per-channel looks in story.py and snack canvases.)
- **Export** (YouTube's recommendations):
  - H.264 High, yuv420p, BT.709 tags, closed GOP of half the frame rate, 2 B-frames, fast start.
  - 1080×1920 at 30 fps for 8–12 Mbps (we use CRF 18 with a 10–16 Mbps cap).
  - 60 fps for physics simulations.
  - AAC 48 kHz, 320 kbps.
  - Loudness −14 LUFS, true peak −1 dBTP [M].
  - **Built:** clipv3 and snack.
- **Soft or low-bitrate video reads as "90s":** never upscale tiny images full-screen. Our v3 sends images under 650 px to framed cards [M/D].

## 11. Instagram Reels packaging
- **Cover:** 1080×1920, but design for the **3:4 grid crop** (safe area about x 65–1015, y 270–1250). Bold, readable at small size [M].
- **Caption:**
  - The hook line with keywords first (Instagram search reads captions).
  - Then 1–2 lines, any campaign-required tags verbatim, and the disclosure if paid.
  - **At most 5 hashtags**; Mosseri says they don't add reach [M].
- **Originality:** never post the YouTube file byte-for-byte. Vary the hook wording and trim slightly, never use watermarks, and never repost others' content (10 unoriginal posts in 30 days stops recommendations) [M].
- **Trial Reels** to test hooks on non-followers [M].

## 12. Gaps
- Exact fonts, sizes and loudness of top channels are estimated from preview frames.
- Retention benchmarks per niche will come from our own analytics.
- Chatterbox and Indic Parler-TTS quality is untested.
- The ACE-Step repo licence still needs a direct check.
