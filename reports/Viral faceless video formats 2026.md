# Viral faceless video formats 2026

*Research for Clip Factory, 10 Nov 2026. Detailed notes with every source link are in
`research_notes/Viral faceless video formats 2026/` (12 files). Confidence: H = high, M = medium, L = low.*

## 1. Bottom line
- **Our v2 videos match what YouTube no longer pays for.** Since 15 Jul 2025, YouTube's "inauthentic content" rule names "image slideshows, templated storylines, or scrolling text with minimal narrative" as non-monetizable, and reviews are channel-wide (H). Our story Shorts (tilted photo cards, Ken Burns zooms, red text screens, giant Anton captions) are that pattern.
- **What wins in 2025–26 is motion and a real story.** Examples:
  - 3D-animated micro-stories: Zack D. Films (~29.6M subscribers), His Story (+480K subscribers in 28 days).
  - Documentary collage, original game simulations, and footage-free explainers with their own creative device (HISHE, Alt Shift X).
  - Clean, minimal podcast clips.
- **Every channel needs its own look, recurring character and voice.** YouTube's spam policy names "channels that use the exact same background music and repetitive AI generated imagery across many videos" (H).
- **Long-form is where the money is from 2027 (VERIFIED from YouTube's own blog text, saved in research_archive/…/evidence).** From 1 Feb 2027:
  - Only channels with 10M qualified Shorts views in the last 90 days share Shorts ad revenue.
  - Others keep long-form earnings.
  - New applicants need 8,000 watch hours/365 days or 20M Shorts views/90 days.
  - Shorts RPMs are pennies, while US finance long-form earns about $15–26.

## 2. Rules that shape every format
| Rule | What it means for us | Conf. |
|---|---|---|
| Inauthentic content (Jul 2025, clarified Jul 2026) | No slideshows or templates. Every video needs a distinct storyline and real narrative. AI "podcast hosts giving financial guidance" are named as not allowed. | H |
| Spam / coordinated networks | Different music, imagery and voice per channel; never the same template across our 10 channels | H |
| AI disclosure | Label realistic AI. Clearly animated content needs no label. India's IT Rules (20 Feb 2026) also require labels on AI audio/video. | H |
| Shorts length and music | Shorts can be up to 3 min, but a Short over 1 min with any Content ID claim is blocked. Our footage-free Shorts can run 60–180 s. | H |
| Shorts series | Seasons and episodes launched 23 Sep 2026; use them for "Part 1/2/3" | H |
| Instagram originality | 10+ unoriginal posts in 30 days stops recommendations; reposts and watermarks are demoted | H |
| Enforcement | Fake-trailer channels terminated Dec 2025; 16 big AI-slop channels removed Jan 2026 (4.7B views); faceless channels report demonetization waves | M–H |

## 3. Playbook per channel

### #1 Hot Take HQ (US podcast clips for campaigns)
- **What top clips look like** (H/M):
  - full-screen active speaker, with eyes on the upper third
  - a hard cut on real speaker turns, and a stacked split only during rapid exchanges
  - 1.12–1.15× snap punch-ins on payoff lines, held 3–4 s
- **Captions:** 2–3 word chunks, white with a thin outline and one accent colour.
- **Hook:** a 4–8-word headline from frame 0.
- **Banned looks:** full-clip blurred letterbox, bouncing yellow text, emoji spam, gameplay split-screen.
- **Length:** 18–58 s; YouTube cap 59 s unless the campaign confirms no Content ID.
- **Campaign rules:** disclosure on screen from the start, submit within 30 min, credits copied word for word.
- **Status:** **BUILT** (`engine/clipv3.py`): active-speaker detection, speaker cuts, split, punch-ins, pause tightening, white hook box, accent captions, disclosure pill, -14 LUFS.

### #2 Unsolved After Dark (US mysteries)
- **Winners:**
  - 3D micro-stories, 35–50 s, cutting about once a second
  - human-made documentary long-form (fern, Nexpo)
- **Faded:** the 2025 "POV: you wake up in 1351" AI wave; similar YouTube POV Shorts mostly get under 1.3K views. Its 2026 successor is the AI time-travel host (Chloe VS History, 425K subs) (M).
- **Shorts anatomy** (measured from about 35 videos):
  - no title card; the first line is the climax
  - "You see," backstory at 4–8 s, then "But," twist, then an ironic payoff with no call to action
  - narration at 170–200 words per minute
  - small captions: 2–3 plain white words at about 77% height, about 64 px
- **Money:** long-form compilations of 20–40 min, with "Pt. 2" / "Vol. N" series, and matching Shorts within 3 days of each long video.
- **Decision:** a micro-story Short built from consistent-style AI stills (needs the Cloudflare keys) with 2.5D parallax, documentary-collage graphics, small captions and the climax-first structure, plus a weekly 20–30 min case file.

### #3 Clutch Tales (US sports stories, no footage)
- **The risk with footage:** most big channels use match footage and get claims or removals, and BCCI forced a podcast to delete all its IPL 2025 videos (H).
- **Footage-free wins:**
  - stat-graphics and cut-out Shorts (Athletic Interest, 4.8M on one)
  - illustrated documentaries
- **Hook:** stakes plus an exact number in the first 1–2 s, e.g. "When Dhoni on strike & India need 15 runs" (14.1M) or "146-4, chasing 326" (H).
- **Decision:**
  - formats: Clutch-Moment Short, Stat-Collage Short, long-form Illustrated Documentary
  - graphics kit: scoreboard bar, "NEED X OFF Y" card, pitch map, charts, our own newspaper mock-up, quote cards
  - no photoreal likeness of real athletes

### #4 Ending Decoded (movie explainers, no clips)
- **Verdict: conditionally viable.**
- **Who leads:** clip-based leaders (Film Theorists, FoundFlix) still show demand. Footage-free winners all have a creative device (HISHE: original animation; Alt Shift X: graphics).
- **Format and mix:** an "Evidence Board Decode" look. About 50% new-release endings, 25% film-science theories, and 25% public-domain classics. 1930 US films entered the public domain on 1 Jan 2026, so we can use real footage from original prints.
- **Never:**
  - package anything as official
  - studio stills or posters
  - actor likenesses
  - near-duplicate uploads

### #5 Money Cheat Codes (US money/tech)
- **Leaders:**
  - How Money Works: median about 892K views per video
  - Economics Explained
  - The Infographics Show
  - Breakout: Primate Economics, a crude cartoon monkey explaining money with bananas; its Short was simply the first 56 s of a long video (15.7M)
- **Losing:** generic stickman templates, and high-volume posting.
- **Measured anatomy:**
  - the picture changes about every 2 s
  - **no karaoke captions**; on-screen numbers, highlighted proof screenshots and name cards carry the meaning
  - looping endings
  - narration at 120–150 wpm for cartoon styles, 170–220 for documentary styles
- **Compliance:** never an AI "adviser"; frame as explainers or stories.
- **Decision:** a recurring original cartoon character plus animated charts and proof screenshots. Long-form first, with Shorts cut from it.

### #6 Itihaas Ke Raaz (Hindi mythology/history)
- **Market:** older mythology channels are fading outside festivals (their best hits are from 2021–23). The AI-history boom stalled (HistoryvideoAI). Studios show demand (JioStar's AI Mahabharat got 26.5M views but was mocked for errors) (M).
- **Titles:** Devanagari curiosity gaps, e.g. "माता सीता के 2 नहीं बल्कि 3 पुत्र थे…".
- **Backlash cases:** police complaints over fabricated AI rituals, FIR demands. Devotees reject pale or Westernised deities and invented divine speech.
- **Legal:** BNS Section 299 (religious sentiment) and the IT Rules AI label.
- **Decision:**
  - respectful, accurate stories with consistent deity designs
  - public-domain Raja Ravi Varma paintings plus AI stills, with 2.5D parallax
  - deep male narration; original drone and conch sound
  - Devanagari captions with letter-spacing 0
  - Shorts as trailers for numbered long-form series (भाग 1/2)

### #7 Cricket Ke Kisse (Hindi cricket stories)
- Same hook rule: stakes plus an exact number.
- **Captions:** viral Hindi Shorts use **Roman-script Hinglish captions** over Hindi narration, with Devanagari on thumbnails and punch cards. Test both.
- **Rights are tightening:** Delhi High Court likeness orders for Gavaskar, Gambhir and Yuvraj cover AI. AI cartoons of real cricketers get big views but are exactly what those orders target, so we avoid them.
- **Fonts:** Mukta 800 / Baloo 2 for Hindi, Teko / Rajdhani for scoreboard numbers.
- **Note:** the name "Cricket Ke Kisse" already exists as two tiny channels.
- **Decision:** a Hindi Kissa Short plus an illustrated long-form documentary, using our cricket graphics kit.

### #8 Picture Abhi Baaki Hai (Bollywood)
- **Verdict: not viable as "Bollywood facts".** Star-photo facts channels are fading, and there are personality-rights orders for many stars, including against films about them.
- **Decision:** pivot to **box-office and film-business economics plus silent-era cinema history**, with no star likeness, voices, catchphrases or gossip.

### #9 Brain Snack (teens/adults)
- **Measured winners:**
  - escalating escape and break simulations
  - multiply-and-reveal loops
  - character-vs-character battles
  - timed quiz ladders
  - Zack D. Films-style 3D facts
- **Italian brainrot lessons:**
  - readable hybrid characters with chantable names
  - a roster that fans can rank
  - human-designed characters, since AI-made ones get little copyright protection
- **Risks:**
  - the same rules and outcome every video counts as templated
  - pastel colours, cute blobs and nursery chants push the channel toward "made for kids"
- **Status: BUILT (`engine/snack/`).** Five rotating formats, with a new rule combination every video and public-domain melodies played by collisions:
  - Attempt Spiral
  - Multiply & Reveal
  - Snack Squad VS (with a season table)
  - Brain Quiz Ladder (AI-checked answers)
  - Read-it-if-you-can

### #10 Bloop & Friends (Made for Kids)
- **Market:** growth is in calm, research-based content (Ms Rachel 13M → 21.5M) while Cocomelon's monthly views fall.
- **The crackdown on AI kids' videos:** the NYT (Feb 2026) found over 40% of recommended videos for toddlers were AI. YouTube's quality rules reward "enriching", complete-narrative content.
- **Legal:** COPPA penalties are up to $53,088 per violation, and Made for Kids switches off comments and personalised ads.
- **Song traps:** "Twinkle Twinkle" is safe. "Wheels on the Bus" (1937, likely still protected outside the US), "If You're Happy…" (1971 filing) and "Lakdi Ki Kaathi" (a 1983 film song) are not.
- **Decision:**
  - a calm preschool sing-along with 4–6 s shots
  - pauses for kids to answer
  - our own arrangements of public-domain melodies
  - Shorts only as trailers
- **Open problem:** the singing voice. A human singer on a buy-out contract is best.

## 4. Thumbnails, titles and covers
- **Less text wins** in 1of10's study of 300K+ videos (thumbnails with text averaged about 19% fewer views; the best have no text or under 10 characters).
- **But Indian outliers use 2–5 words:**
  - English caps for explainers
  - Devanagari for mythology
  - mixed scripts for Lallantop and facts channels
- Movie and money winners often have no text at all (H/M).
- **YouTube's Test & Compare** now picks winners by watch time, so misleading thumbnails lose (H).
- **Shorts covers barely matter:** about 99.9% of Shorts views come from the feed, so the first frame is the real cover. Custom Shorts thumbnails started rolling out on 25 Jul 2026, from YouTube Studio on desktop only (H).
- **Instagram:** profile grid covers are cropped to 3:4 (safe area about x 65–1015, y 270–1250 at 1080×1920). Hashtags are capped at 5, and they don't increase reach (H/M).
- **Our old "tilted photo card with red arrow" style is dated.** The modern news-explainer look: a text panel, a full-bleed cut-out, one highlighted payoff word, and arrows only to point at proof.

## 5. Tools and throughput (₹0)
See `free_production_toolchain.md`.
- **Built on our CPU:** numba physics, 2.5D parallax (Depth-Anything-V2-Small, Apache; Base and Large are non-commercial), active-speaker clips.
- **Next:**
  - Cloudflare FLUX.1-schnell / klein-4B: about 95–170 free images a day, needs the owner's keys
  - Colab for Chatterbox voice and a few Wan video shots
  - our own motion-graphics kit
- **Kaggle is excluded** (non-commercial terms).
- **Throughput:** about 2–3 h of overnight rendering a day for about 10 Shorts plus long videos, which fits the week-ahead batch.

## 6. What changes in our system
| Area | Change | Status |
|---|---|---|
| Brain Snack | v3 rotating game formats | Built |
| Podcast clips | v3 clean speaker-cut style | Built |
| Weekly operations | Week-ahead plan → make → phone approval page | Built |
| Campaign money | Safety gate, ledger, exposure caps, scam screening | Built |
| Story channels | Parallax engine built. Next: story renderer v3 with per-channel identities, documentary-collage kit, climax-first scripts, small captions, AI stills | In progress |
| Thumbnails | v3 templates per channel from the research | To do |
| Kids channel | Sing-along pipeline; singing voice to solve | To do |

## 7. Main gaps
- Exact caption fonts, sizes and audio levels of top channels are estimates from preview frames.
- No reliable Hindi RPMs.
- The Feb 2027 Shorts rule needs a final check on YouTube's own pages.
- US data is thinner, because the crawl ran from India.
- AI video speeds on a free T4 are untested.
