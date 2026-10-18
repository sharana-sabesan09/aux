# PRD: Aux, a private DJ for your Spotify that learns from every skip

LA Hacks AI Hackathon 2026. Target tracks: **veri.studio (primary)**, Paper Best Designed Hack. Stretch: MLH Best Use of ElevenLabs.
Deadline: Sunday Oct 18, 12:00 PM PDT.

## 1. One-liner

Aux passively observes your context (time of day, where you are, how fast you're moving, what's on your calendar, how packed your day has been, the weather) and queues the right songs on your real Spotify. **It never asks the user anything.** Every skip is a training signal: Aux turns skips into preference data and retrains its own model on Veri.

The brain is a small open model (Qwen3-1.7B) fine-tuned on Veri: first taught the task by a large teacher model (SFT), then tuned to *my* taste from A/B picks and real skips (DPO).

## 2. Why Veri (the pitch)

Veri's mission is helping companies "continually improve their AI models as their product gets used." Aux is that loop in miniature:

```
listen -> skips + full plays logged with context -> preference pairs -> DPO on Veri -> better DJ -> listen
```

- **Rules can't do it.** "Orgo midterm in 40 min", "5th event today, 3 back-to-back", "on the 5 at 70 mph, left home 10 min ago" need language understanding and inference about how you probably feel.
- **Taste is personal.** A frontier model gives everyone the same vibe. DPO on my picks and skips makes the model agree with me.
- **Private and cheap.** Calendar, location and listening history are sensitive, and the DJ decides every minute. A 1.7B open model (weights on Hugging Face) can run locally and costs a fraction of a frontier API per call.
- **Headline numbers:** preference agreement (base vs SFT vs DPO vs teacher), JSON validity, p50/p95 latency, cost per 1k calls, and agreement before vs after the skip-retrain round.

## 3. Scope

### In scope (MVP)
1. Spotify login (OAuth PKCE) and three working calls: read library, add to queue, read playback state.
2. Catalog: user's saved + top tracks, each tagged once by the teacher model.
3. Context collector (mobile-friendly web page, no user input).
4. Vibe model: context text -> JSON vibe spec.
5. Selector: vibe spec -> track URI -> Spotify queue.
6. Skip detection by polling playback; log every play with its context.
7. A/B labeling page (plays candidates through Spotify) for the first DPO set.
8. Skip -> DPO pair builder and a retrain script.
9. Replay mode + sliders for judging.
10. Eval + benchmark charts.

### Stretch
- ElevenLabs voice for the `dj_line` (plays in the browser, not Spotify).
- Run the tuned model locally via Ollama to demo "nothing leaves your laptop".

### Out of scope
- Playlist creation (dev-mode 403 reports; queueing is the better DJ UX anyway).
- Spotify audio features / recommendations / previews (removed for new apps).
- Multi-user, accounts. Phone-only data (Apple Health, screen time): pitch as next steps.

## 4. Spotify integration

**App setup (developer.spotify.com/dashboard):** Create app, select Web API, redirect URI `http://127.0.0.1:8000/callback` (must be `127.0.0.1`, not `localhost`). App owner account must have **Premium**. Dev mode allows up to 5 users; add any teammate's account under User Management.

**Scopes:** `user-library-read user-top-read user-read-playback-state user-modify-playback-state user-read-currently-playing user-read-recently-played`

**Endpoints used (2026 versions):**

| Purpose | Call |
|---|---|
| Saved tracks | `GET /me/tracks?limit=50&offset=N` (page through all, cap 600) |
| Top tracks | `GET /me/top/tracks?time_range=medium_term&limit=50` and `short_term` |
| Recent history backfill | `GET /me/player/recently-played?limit=50` |
| Playback state | `GET /me/player` (device, track, progress_ms, is_playing) |
| Queue a track | `POST /me/player/queue?uri=spotify:track:...` |
| Jump to it | `POST /me/player/next` |
| A/B previews | `PUT /me/player/play` with `{"uris": [...], "position_ms": 30000}`, pause after 15 s |

**Rules:**
- Spotify's queue can't be cleared or reordered via API. **Aux keeps at most ONE track queued ahead.** Track what Aux queued in memory.
- All calls go through one `spotify.py` client: auto-refresh tokens, retry on 429 using `Retry-After`, treat `"reason": "QUOTA_EXCEEDED"` as a hard stop and show it in the UI.
- No active device (404 / `NO_ACTIVE_DEVICE`) -> UI banner "Open Spotify on your phone or laptop".
- Tokens live in `.tokens.json` (gitignored).

## 5. Context signals (all passive)

| Signal | Source | Notes |
|---|---|---|
| Time | `Date()` | Bucket: early morning, morning, afternoon, evening, late night. Include weekday. |
| Speed | `navigator.geolocation.watchPosition` -> `coords.speed` | If null, compute from consecutive fixes. Bucket: still, walking, biking, city driving, freeway. |
| Place | GPS vs `data/places.json` (name, lat, lon, radius_m) | home, Geisel, gym, RIMAC... Unknown -> "unknown, moving/still". |
| Motion pattern | GPS history, last 30 min | "stationary 2 h then started driving", "walking 12 min". |
| Calendar | Google Calendar secret iCal URL, parsed with `icalendar` | Current event + next within 2 h (title, minutes until start). Fallback `data/demo/events.json`. |
| Day load (inferred mood) | Same calendar | Events so far today, back-to-back count, minutes since last ended, hours until first event tomorrow. |
| Weather | Open-Meteo (free, no key) | Temp, condition, is_day. |
| Listening | Play log (section 8) | Last 5 plays: finished vs skipped, at what second, and their vibe tags. |

No mood box, no prompts. Mood is inferred.

Prompt example:
```
Sat 7:42 PM | freeway, 68 mph, started driving 10 min ago after 2 h at home | 64F clear, dark
today: 5 events, 3 back-to-back, last ended 40 min ago | next: "dinner w/ Priya" in 25 min
recent: finished 3 (chill, indie), skipped 2 (hype, both < 20 s)
```

## 6. Model I/O

**System prompt:** "You are a DJ. Given the listener's context, output only JSON describing the music that fits right now."

**Output (strict JSON):**
```json
{"energy": 0.0-1.0, "valence": 0.0-1.0, "bpm_min": int, "bpm_max": int,
 "tags": ["up to 3 from TAG_VOCAB"], "dj_line": "max 15 words, casual"}
```

`TAG_VOCAB`: fixed list of about 25 (chill, focus, hype, warm, dreamy, dark, acoustic, electronic, hip-hop, r&b, indie, lo-fi, jazz, ambient, pop, rock, funk, soul, latin, k-pop, cinematic, sad, romantic, nostalgic, party). Same vocab used to tag the catalog.

Pydantic validation. Invalid -> retry once -> fall back to last good spec.

## 7. Catalog (`scripts/build_catalog.py`)

1. Pull saved + top tracks (dedupe by URI, cap 600). Keep uri, name, artists, album, release year, duration_ms, explicit.
2. Teacher tags each track in batches of 25 (Anthropic API): `{uri, energy, valence, bpm_min, bpm_max, tags, confidence}`. Instruct: if you don't recognize the song, estimate from artist/album/era and set `confidence: "low"`.
3. Drop low-confidence tracks if the catalog stays above 200.
4. Save `data/catalog.json`. Print tag coverage; flag any tag with fewer than 8 tracks.

**Selector:** score = weighted distance on (energy, valence, BPM midpoint inside range) + bonus per matching tag. Exclude the last 30 played and anything skipped in the last 2 h. Random pick from the top 5.

## 8. Play loop and skip detection (`app/dj.py`)

Background loop every 5 s:

1. `GET /me/player`. Detect track change.
2. On a track change, classify the previous play:
   - **skip** if it ended with `progress < 70%` of duration and more than 10 s left,
   - **strong skip** if within the first 30 s,
   - **finish** otherwise.
   Append to `data/play_log.jsonl`: `{ts, uri, outcome, listened_ms, context_text, spec_at_time, queued_by_aux}`.
3. Plays the user started themselves (`queued_by_aux: false`) are logged but never used as negatives.
4. **Recompute the vibe** every 60 s or on a context event: speed bucket change held 30 s, place change, calendar event starting within 10 min, 2+ skips in a row.
5. **Queueing:**
   - Normal: when the current track has under 25 s left and nothing is queued, queue the selector's pick.
   - Big shift (energy or valence changes by more than 0.35, or a strong skip): queue the pick and call `next` immediately.

## 9. Training plan (Veri)

Model `Qwen/Qwen3-1.7B`, 1x `L4-24GB`, provider `aws`, LoRA (`lora_rank = 16`). Every run pushes merged weights to a **public** HF repo (`[hf_push] artifact = "merged"`, `private = false`). Log every job id and repo in `results/runs.md`.

### Stage 1: SFT (task + format)
1. `scripts/gen_contexts.py`: about 1,000 synthetic contexts covering all signals (times, speeds, places, motion patterns, realistic calendar titles, day-load stats, recent finish/skip patterns).
2. `scripts/label_teacher.py`: teacher writes the vibe spec for each. Validate, drop invalid. 10 concurrent.
3. `data/sft.jsonl`, one format only: `{"prompt": [system, user], "answer": "<json>"}`. `veri datasets check`; if SFT wants chat format, convert to `{"messages": [...]}`.
4. Hold out 100 as `data/sft_eval.jsonl`.
5. `configs/sft.toml`: `method.type = "sft_text"`, 2 epochs. Push to `<hf-user>/aux-sft`.

### Stage 2: DPO round 1 (A/B taste)
1. `scripts/gen_pairs.py`: 250 fresh contexts. Candidate A = teacher spec; candidate B = spec with energy/valence shifted by 0.3+ or swapped tags. Resolve each to its top catalog track.
2. `/label` page: shows context, two track cards (art, name, artist). Press A or B to hear a 15 s clip through Spotify; press 1, 2 or space (skip). Target 200 labels in about 60 min -> `data/prefs.jsonl`.
3. 160 train / 40 held out (`data/prefs_eval.jsonl`).
4. `data/dpo.jsonl`: `{"prompt": [...], "chosen": "<spec>", "rejected": "<spec>"}`.
5. `configs/dpo.toml`: `method.type = "dpo"`, `[model] base = "<hf-user>/aux-sft"`. Push to `<hf-user>/aux-dpo`.

### Stage 3: DPO round 2 (skips, the learning loop)
1. `scripts/skips_to_pairs.py`: from `play_log.jsonl`, for each Aux-queued **skip**, find an Aux-queued **finish** within 15 min with a similar context. Pair: prompt = skip's context, chosen = finished track's catalog spec, rejected = skipped track's catalog spec. Strong skips first.
2. Merge with the round 1 train set; dedupe.
3. `make retrain`: build pairs -> upload -> launch DPO from `aux-dpo` -> push `aux-dpo-r2` -> redeploy.
4. Even 20 to 40 real pairs is enough to **show the loop working** in the demo.

**Fallbacks:** if DPO fails, ship `aux-sft` and report SFT gains. If there aren't enough skips by Sunday 8 AM, demo round 2 as "loop ready, here are the pairs it built" instead of a finished run.

## 10. Evaluation (`scripts/eval.py`)

Compared: base, aux-sft, aux-dpo, aux-dpo-r2 (if exists), teacher.
1. JSON validity % on `sft_eval.jsonl`.
2. Teacher agreement on `sft_eval.jsonl`: MAE on energy, valence, BPM midpoint.
3. **Preference agreement %** on `prefs_eval.jsonl` (+ held-out skip pairs if any): spec at temperature 0; agree if closer to `chosen` than `rejected` in normalized (energy, valence, bpm_mid). Headline number.
4. Latency p50/p95 over 100 warm calls; cost per 1k calls (Veri $/GPU-hour vs teacher token pricing).

Output `results/metrics.json` + `results/*.png`, shown at `/results`.

## 11. Architecture

```
browser (web/index.html, label.html, results.html; vanilla JS)
   |  POST /context every 15 s (GPS, speed)       GET /state (now playing, vibe, log)
FastAPI (app/main.py)
   |-- spotify.py   OAuth PKCE, token refresh, queue/next/play, 429 handling
   |-- context.py   prompt builder (calendar, weather, places, day load, recent plays)
   |-- model.py     OpenAI client -> https://api.veri.studio/v1/deployments/{VERI_DEP_ID}
   |                (or teacher via Anthropic when MODEL=teacher)
   |-- selector.py  spec -> track URI from data/catalog.json
   |-- dj.py        5 s poll loop, skip detection, queueing, play_log.jsonl
   |-- tts.py       (stretch) ElevenLabs
```

- Python 3.11: fastapi, uvicorn, pydantic, httpx, openai, anthropic, icalendar.
- Frontend: plain HTML/JS/CSS, mobile-first. Phone GPS needs HTTPS: tunnel with `cloudflared` for live use. Replay mode works on localhost.
- `.env`: `SPOTIFY_CLIENT_ID`, `VERI_API_KEY`, `VERI_DEP_ID`, `ANTHROPIC_API_KEY`, `ICAL_URL`, `MODEL` (teacher|veri), `ELEVENLABS_API_KEY`. Gitignore `.env`, `.tokens.json`, `data/play_log.jsonl`.
- Veri client handles 503 + `Retry-After` (waking deployment): retry up to 90 s, UI shows "waking up the DJ".

```
aux/
  PRD.md  Makefile  .claude/skills/veri/SKILL.md
  app/ main.py spotify.py context.py model.py selector.py dj.py tts.py schemas.py
  web/ index.html label.html results.html app.js style.css
  scripts/ build_catalog.py gen_contexts.py label_teacher.py gen_pairs.py skips_to_pairs.py eval.py
  configs/ sft.toml dpo.toml dpo_r2.toml
  data/ places.json catalog.json demo/drive_trace.json demo/events.json
  results/
```

## 12. UI

**Main (`/`):**
- Now playing (from Spotify): album art, title, artist, progress. "Queued next by Aux" card.
- Context chips: time, speed + bucket, place, next event, weather, day load, inferred mood ("drained", "wired").
- Current vibe: energy and valence bars, BPM range, tags, `dj_line`.
- **Learning panel:** "37 plays logged · 9 skips · 6 new training pairs since last train" + last retrain time and model version.
- Live / Replay toggle. Replay feeds `demo/drive_trace.json` at 4x with sliders (speed, time) and a calendar-event picker, still queueing to real Spotify. Judging only; the live product has no controls.
- Badge: "model: aux-dpo · 212 ms".

**Design:** dark, calm, one accent, large type, readable at arm's length (Paper prize).

## 13. Milestones (now -> Sunday noon)

| By | Milestone | Done when |
|---|---|---|
| Sat 6:30 PM | M0 Setup | `veri whoami` ok + credits; Spotify app created; OAuth works; saved tracks read, one track queued, playback state read |
| Sat 7:30 PM | M1 Catalog | `catalog.json` with 200+ tagged tracks, tag coverage printed |
| Sat 8:00 PM | M2 **SFT launched** | `sft.jsonl` passes check, job `running` |
| Sat 10:00 PM | M3 DJ MVP | Replay mode queues real Spotify tracks, skips logged, `MODEL=teacher` |
| Sat 11:30 PM | M4 **DPO r1 launched** | 200 A/B labels, job `running` from `aux-sft` |
| Sun 8:00 AM | M5 Live use | Switch to `MODEL=veri`; app has been running live (late night + morning) logging skips |
| Sun 9:00 AM | M6 Eval | `metrics.json` + charts for base/sft/dpo/teacher |
| Sun 10:00 AM | M7 **Retrain r2** | `make retrain` launched from real skips (or pairs shown if too few) |
| Sun 11:00 AM | M8 Polish | Results + learning panel, video recorded |
| Sun 11:45 AM | Submit | Devpost, repo public, deployments stopped after judging |

## 14. Instructions for Claude Code

- Read this PRD and `.claude/skills/veri/SKILL.md` before writing code.
- Build milestone by milestone; meet each "done when" before moving on. Ask before changing scope.
- Spotify: verify the three M0 calls before building anything on top. Never queue more than one track ahead.
- Veri: `veri whoami` at session start, `veri jobs estimate` before each job, `veri datasets check` before each upload, one prompt format per JSONL.
- Deployments: `--gpu-type L4-24GB --min-replicas 0 --max-replicas 1`. List deployments at the end of each session.
- Never delete Veri jobs, datasets, deployments or models without asking.
- Concise code, no boilerplate, no extra frameworks.

## 15. Demo script (2 min)

1. (15 s) Your music doesn't know you're about to walk into a midterm, and it never learns from your skips.
2. (60 s) Replay on real Spotify: late-night freeway -> energy up; traffic -> eases down; "Orgo midterm in 20 min" -> focus; midterm ends after 4 back-to-back -> infers "drained", goes warm and mellow. Skip two tracks live -> it backs off, and the learning panel ticks up.
3. (30 s) Results: base vs SFT vs DPO agreement, latency and cost vs teacher; round 2 retrained on real skips.
4. (15 s) Every skip makes it better. Private, personal, open weights.

## 16. Risks

| Risk | Mitigation |
|---|---|
| No Premium / no active device | Confirm Premium in M0. Keep Spotify open on the demo laptop. |
| Spotify 429 / QUOTA_EXCEEDED | 5 s polling only, one queue call per decision, back off on `Retry-After`. |
| Teacher mis-tags unknown songs | `confidence` field, drop lows, spot-check 20. |
| Veri capacity | Launch SFT by 8 PM; follow the skill's "Getting unstuck". |
| Too few skips for round 2 | Run the app live tonight while working; fallback is showing pairs + launched job. |
| DPO shows no gain | Clear A/B contrasts (0.3+ shift). Report honestly; SFT gains still stand. |
