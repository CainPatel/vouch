# Vouch — Overnight Build Progress Log

## 2026-11-14 00:06 PST — Milestone M0 Started
- Read `SPEC.md` in full and inspected environment.
- Confirmed installed tools: Python 3.14, `uv`, `node`/`npm`, `docker` (daemon running), `ffmpeg`, `git`. `gcloud` is not installed (per run rules: do not install or log in; verify Docker locally and put exact deploy commands in `MORNING.md` and `BLOCKED.md`).
- Note on macOS Python SSL certificates: python.org framework Python lacks system CA bundle by default; resolved cleanly by using `certifi` (`SSL_CERT_FILE`) at process startup and managing `.venv` with `uv` (Python 3.12).
- Verified `GEMINI_API_KEY` from `.env` by listing available models on `generativelanguage.googleapis.com/v1beta/models`:
  - Live voice model confirmed: `models/gemini-3.8-live` (`bidiGenerateContent`, supports native 16kHz PCM in / 24kHz PCM out, input & output audio transcription, and `NON_BLOCKING` function calling with `scheduling`).
  - Post-call report model confirmed: `models/gemini-4-carbon` (`Gemini 4 Carbon`, `generateContent`).
  - TTS model for scripted caller clips confirmed: `models/gemini-3.8-flash-tts` (`Gemini 3.8 Flash TTS`).
- Read current Gemini Live API docs (`live-guide`, `live-api/tools`, `gemini-3.8-live`), Gemini 4 Carbon docs, and Gemini 3.8 TTS docs.

## 2026-11-14 00:10 PST — Milestone M0 Complete (`m0`)
- Scaffolded FastAPI backend (`server/`), static assets (`static/`), `Makefile`, `pyproject.toml`, `.gitignore`, `.env.example`, `BLOCKED.md`, `server/contacts.json`, and `server/prompts/screener.md`.
- Verified `make run` serves `/` ("Start demo") and `/api/health` in both live discovery mode (`gemini-3.8-live`, `gemini-4-carbon`, `gemini-3.8-flash-tts`) and mock mode (`VOUCH_MOCK=1`).
- Verified `.gitignore` excludes `.env`.

## 2026-11-14 00:20 PST — Milestone M1 Complete (`m1`)
- Built room state machine (`server/models.py`: `idle -> screening -> verifying -> passed | blocked | message_taken -> idle`), `RoomHub` (`server/hub.py`), mock session (`server/mock_session.py`), and Gemini 4 Carbon background post-call report (`server/report.py`).
- Wired all 5 routes (`/`, `/demo`, `/caller`, `/senior`, `/family`), inline SVG QR code endpoint (`/api/qr`), WebSocket hub (`/ws`), AudioWorklet processors (`pcm-capture-worklet.js`, `pcm-playback-worklet.js`), and `audio-engine.js`.
- Enforced 5-room concurrent active cap (with idle room eviction), 3-minute call timeout, and per-IP call-start rate limiting.
- Created `MORNING.md` per run rules.
- Unit tests (`tests/test_unit.py`): 5/5 green (`make test`).

## 2026-11-14 00:33 PST — Milestone M2 Complete (`m2`)
- Generated all 3 scripted caller clips (`grandson_bail.wav`, `bank_fraud.wav`, `pharmacy.wav`) under `static/audio/` using Gemini TTS (`gemini-3.8-flash-tts`) with stock voices (`Puck`, `Charon`, `Zephyr`).
- Built `server/live_session.py` (`GeminiLiveScreenerSession`) connected to `gemini-3.8-live` with 16kHz PCM streaming input, 24kHz PCM streaming output, input & output audio transcriptions, automatic VAD (`silence_duration_ms=450`), and immediate pending tool acknowledgement + client-turn verification outcome injection.
- Verified `scripts/audio_smoke.py` (`make smoke`):
  - Caller transcript: `"Grandma, it's Jake. I'm in trouble. I need $4,000 for bail. Please don't tell mom."`
  - Pre-tap assistant hold speech: `"This is Ruth's assistant. One moment while I confirm with Jake."` (3.75s audio)
  - Tool call: `request_family_verification(claimed_name='Jake', relationship='grandson', ask='bail money', amount='$4,000')`
  - Post-tap assistant speech: `"Jake says he isn't calling. Goodbye."` (3.74s audio)
  - Latency: `speech_to_first_audio_s = 0.227s`, `tap_to_first_audio_s = 0.689s` (target < 1.5s).

## 2026-11-14 00:54 PST — Milestone M3 Complete (`m3`)
- Connected `AudioWorkletNode` (`pcm-capture-processor`) through a zero-gain sink to `AudioContext.destination` so Chromium's WebAudio graph pulls mic/clip samples continuously.
- Verified Chromium Secure Context requirement (`http://localhost:<port>` rather than `http://127.0.0.1:<port>`) and Chromium 159 `--use-file-for-fake-audio-capture=<wav>` format.
- Added caller hold-mute while `request_family_verification` is active so background caller noise/loops never interrupt the assistant's hold or closing speech.
- Passed `tests/test_hero_e2e.py::test_hero_fake_mic_once` end-to-end in 15.57s:
  - `claimed_name`: `Jake`
  - `verdict_text`: `Blocked: someone impersonating Jake asked for $4,000.`
  - `speech_to_first_audio_s`: `1.445s`
  - `tap_to_first_audio_s`: `0.502s`
  - `post_tap_played_s`: `1.11s` (> 1.0s played in browser AudioWorklet)

## 2026-11-14 01:02 PST — Milestone M4 Complete (`m4`)
- Built `scripts/run_eval.py` running all 3 scripted scenario clips through `/demo` + 10 consecutive Playwright fake-microphone hero browser runs.
- **M4 Baseline Metrics:**
  - Hero pass rate: **10 / 10 (100%)**
  - Scripted scenarios correct action: **3 / 3** (`grandson`: blocked after verification, `bank`: blocked immediately, `pharmacy`: passed through ringing Ruth)
  - Median `speech_to_first_audio_s`: **1.725s** (range `1.466s`–`2.298s`)
  - Median `tap_to_first_audio_s`: **0.782s** (range `0.535s`–`1.372s`; target < `1.5s`)

## 2026-11-14 01:06 PST — Milestone M5 Complete (`m5`)
- Built `Dockerfile` (`python:3.12-slim`), `.dockerignore`, and `scripts/deploy.sh` (with `--allow-unauthenticated --min-instances=1 --max-instances=1 --timeout=3600 --session-affinity --no-cpu-throttling`).
- Verified `.env` is excluded from the Docker image (`test ! -f /app/.env`).
- Ran container locally via `docker run` and passed `tests/test_hero_e2e.py` against the containerized service (`16.06s`, `Blocked: someone impersonating Jake asked for $4,000.`).
- Documented exact 3-command Cloud Run deployment at the top of `MORNING.md` and in `BLOCKED.md` (`gcloud` is not installed on this Mac per run rules).

## 2026-11-14 01:08 PST — Improvement Loop Iteration 1
- **Measured Baseline (from M4 10-run + 3-scenario eval):**
  - Hero pass rate: `10/10`
  - Median `"Not me"` tap -> first assistant audio: `0.782s`
  - Median end of caller speech -> first assistant audio: `1.725s`
  - Scripted scenarios producing correct action: `3/3`
- **Listen-by-Proxy Audit (`artifacts/*_transcript.txt` + `artifacts/screenshots/demo_*.png`):**
  - **Single worst problem a judge would notice:** In `demo_06_pharmacy_passed.png` and `call_93188a93af_transcript.txt`, when `gemini-3.8-live` invoked `pass_through` before speaking, `_on_model_turn_complete` only checked `_post_tap_audio_bytes < 12000` when `_verification_outcome is not None`, so the call closed before the assistant spoke `"This is Ruth's assistant. Thank you — connecting you with Ruth right now."` out loud (`44`-byte WAV, bottom caption stuck on `"Screening incoming call..."`). Also noticed one transcript contained raw ASR control tag `<no speech>{pause}`.
- **Fix Applied:** Require spoken assistant audio (`>= 12000` bytes = `0.25s+`) after any terminal tool call (`pass_through`, `block_call`, `take_message`) before hanging up, and strip `<...>`/`{...}` ASR non-speech markers from transcripts.
- **Re-measured Metrics (Iteration 1):**
  - Hero pass rate: **10 / 10** (held)
  - Scripted scenarios producing correct action + spoken assistant line: **3 / 3** (improved from `2/3` spoken — Pharmacy now speaks `"This is Ruth's assistant. Thank you — I'll connect you with Ruth right now."` out loud before connecting)
  - Median `"Not me"` tap -> first assistant audio: **0.905s** (within normal live Gemini API variance of M4's `0.535s–1.372s` range; well below `1.5s` target)
  - Median end of caller speech -> first assistant audio: **1.797s** (within normal live Gemini API variance of M4's `1.466s–2.298s` range)
- **Decision:** Held `10/10` reliability and fixed silent pass-through hangup (`2/3 -> 3/3` spoken scenarios); committed as `m6-iter1`.

## 2026-11-14 01:16 PST — Improvement Loop Iteration 2
- **Measured Baseline (from Iteration 1):**
  - Hero pass rate: `10/10`
  - Median `"Not me"` tap -> first assistant audio: `0.905s`
  - Median end of caller speech -> first assistant audio: `1.797s`
  - Scripted scenarios producing correct action: `3/3`
- **Listen-by-Proxy Audit (`artifacts/*_transcript.txt` + `artifacts/screenshots/demo_*.png`):**
  - **Single worst problem a judge would notice:** In `call_d9bb7f5ee7_transcript.txt`, the post-tap denial sentence repeated twice with a leaked prefix (`fungal speak: "Jake says he isn't calling. Goodbye."Jake says he isn't calling. Goodbye.`), and `tap -> voice` spent ~0.3s waiting on a redundant post-tap `block_call` round-trip whose `FunctionResponse` re-prompted Gemini to speak while speech had already started.
- **Fix Applied:** Record the authoritative family verification verdict on `RoomSessionController` immediately when `/family` answers, send a single tool-free spoken client turn for the post-tap sentence, and suppress duplicate speech instructions in `block_call` when `_verification_outcome` is already resolved.
- **Re-measured Metrics (Iteration 2):**
  - Hero pass rate: **10 / 10** (held — and 11/11 grandson transcripts matched the exact target lines word-for-word with zero repeats)
  - Scripted scenarios producing correct action: **3 / 3** (held)
  - Median `"Not me"` tap -> first assistant audio: **0.758s** (improved from `0.905s`, `-0.147s`, and faster than M4 `0.782s`)
  - Median end of caller speech -> first assistant audio: **1.584s** (improved from `1.797s`, `-0.213s`, and faster than M4 `1.725s`)
- **Decision:** Every metric held or improved; committed as `m6-iter2`.

## 2026-11-14 01:24 PST — Improvement Loop Iteration 3
- **Measured Baseline (from Iteration 2):**
  - Hero pass rate: `10/10`
  - Median `"Not me"` tap -> first assistant audio: `0.758s`
  - Median end of caller speech -> first assistant audio: `1.584s`
  - Scripted scenarios producing correct action: `3/3`
- **Listen-by-Proxy Audit (`artifacts/*_transcript.txt` + `artifacts/screenshots/demo_*.png`):**
  - **Single worst problem a judge would notice:** On `/demo`, the right-sidebar `LATENCY TELEMETRY` panel stayed blank (`—`) throughout active screening/verification/pass-through (`demo_03`, `demo_05`, `demo_06`) and displayed a bogus `Speech -> voice: 0.01s` in `demo_04` because `caller_speech_ended_at` was overwritten when scripted clip trailing silence finished (`onClipEnded`) and `metrics` was only broadcast on `call_ended`. Also, in-flight pre-tap hold audio chunks could trigger an artificially low `0.045s` `tap -> voice` reading on 1/10 runs.
- **Fix Applied:** Broadcast live `{"type": "metrics"}` WebSocket updates on `/demo` the moment `first_assistant_audio_at` or `post_tap_first_audio_at` is recorded, lock `caller_speech_ended_at` once Vouch begins speaking (removing the late `onClipEnded` override), and gate `post_tap_first_audio_at` on pre-tap turn completion (`_in_model_turn`).
- **Re-measured Metrics (Iteration 3):**
  - Hero pass rate: **10 / 10** (held)
  - Scripted scenarios producing correct action: **3 / 3** (held)
  - Median `"Not me"` tap -> first assistant audio: **0.726s** (improved from `0.758s`, `-0.032s`, with zero fake pre-tap tail outliers; range `0.609s–1.336s`)
  - Median end of caller speech -> first assistant audio: **1.784s** (held within live Gemini API variance of M4 `1.725s` / Iter 1 `1.797s`, and `/demo` screenshots now show accurate live telemetry `1.28s`–`1.60s` and `0.66s` on screen)
- **Decision:** Reliability held `10/10`, `tap -> voice` improved to `0.726s`, and live `/demo` telemetry bug resolved; committed as `m6-iter3`.

## 2026-11-14 01:37 PST — Improvement Loop Iteration 4
- **Measured Baseline (from Iteration 3):**
  - Hero pass rate: `10/10`
  - Median `"Not me"` tap -> first assistant audio: `0.726s`
  - Median end of caller speech -> first assistant audio: `1.784s`
  - Scripted scenarios producing correct action: `3/3`
- **Listen-by-Proxy Audit (`artifacts/*_transcript.txt` + `artifacts/screenshots/demo_*.png`):**
  - **Single worst problem a judge would notice:** In `demo_05_bank_blocked.png` and `demo_06_pharmacy_passed.png`, Jake's Phone top-right status pill stayed stuck on blue `• CALL ACTIVE` after non-family calls blocked or passed through, `Screened Call History` still showed `"No screened calls yet."` while the verdict card was displayed, and Ruth's Phone lacked a prominent incoming-call ringing animation on `passed`.
- **Fix Applied:** Updated `family.js` to transition non-family calls cleanly to `• SCAM BLOCKED` or `• STANDBY`, added an animated incoming-call ringing ripple indicator on Ruth's Phone when `passed` (`senior.html`, `senior.js`, `styles.css`), and updated `Screened Call History` immediately on verdict.
- **Re-measured Metrics (Iteration 4):**
  - Hero pass rate: **10 / 10** (held — 50/50 cumulative across M4 + Iters 1–4)
  - Scripted scenarios producing correct action: **3 / 3** (held)
  - Median `"Not me"` tap -> first assistant audio: **0.685s** (improved from `0.726s`, `-0.041s`)
  - Median end of caller speech -> first assistant audio: **1.904s** (zero backend/audio lines changed in Iteration 4; pure live API variance, with `/demo` scenario screenshots measuring `1.24s` and `1.39s`)
- **Decision:** Reliability held `10/10`, `tap -> voice` improved to `0.685s`, and 1080p `/demo` phone states & ringing indicator look crisp; committed as `m6-iter4`.

## 2026-11-14 01:46 PST — Improvement Loop Iteration 5
- **Measured Baseline (from Iteration 4):**
  - Hero pass rate: `10/10`
  - Median `"Not me"` tap -> first assistant audio: `0.685s`
  - Median end of caller speech -> first assistant audio: `1.904s`
  - Scripted scenarios producing correct action: `3/3`
- **Listen-by-Proxy Audit (`artifacts/*_transcript.txt` + `artifacts/screenshots/demo_*.png`):**
  - **Single worst problem a judge would notice:** In 1 of 10 runs (`call_2d41622876_transcript.txt`), Gemini streamed `"<no"` and `" speech>"` across two separate incremental transcription chunks, bypassing the per-chunk `<...>` regex and appending `[assistant] <no speech>` to the live transcript.
- **Fix Applied:** Buffered trailing unclosed `<...` / `{...` fragments across incremental ASR chunks in `Room.add_or_merge_transcript` (`server/models.py`) and added unit test `test_streaming_asr_split_tag_stripping` (`6/6` unit tests passing).
- **Re-measured Metrics (Iteration 5):**
  - Hero pass rate: **10 / 10** (held — 60/60 cumulative consecutive passes; 13/13 transcripts completely clean with zero ASR tags)
  - Scripted scenarios producing correct action: **3 / 3** (held)
  - Median `"Not me"` tap -> first assistant audio: **0.798s** (held within live Gemini API variance; zero audio/network lines changed)
  - Median end of caller speech -> first assistant audio: **1.873s** (improved from `1.904s`, `-0.031s`)
- **Decision:** Held `10/10` reliability and eliminated split-chunk `<no speech>` artifacts (`13/13` transcripts pristine); committed as `m6-iter5`.

## 2026-11-14 01:52 PST — Improvement Loop Iteration 6
- **Measured Baseline (from Iteration 5):**
  - Hero pass rate: `10/10`
  - Median `"Not me"` tap -> first assistant audio: `0.798s`
  - Median end of caller speech -> first assistant audio: `1.873s`
  - Scripted scenarios producing correct action: `3/3`
- **Listen-by-Proxy Audit (`artifacts/*_transcript.txt` + `artifacts/screenshots/demo_*.png`):**
  - **Single worst problem a judge would notice:** In `demo_04_blocked_with_carbon_report.png`, `Screened Call History` showed two duplicate rows for the same call (both `applyVerdictCard` and `call_ended` prepended an item), and `Report by Gemini 4 Carbon` didn't start generating until after `end_call` (~6.6s after the verdict), delaying the report card ~12s after tapping **Not me**.
- **Fix Applied:** Deduplicated optimistic vs `call_ended` history entries in `senior.js`, triggered the non-blocking Gemini 4 Carbon background report `0.45s` after the verdict is recorded (`server/hub.py`) so it arrives ~3–4s after the verdict without competing with live voice synthesis, and recorded live `metrics` WS events in `tests/test_hero_e2e.py`.
- **Re-measured Metrics (Iteration 6):**
  - Hero pass rate: **10 / 10** (held — 70/70 cumulative consecutive passes)
  - Scripted scenarios producing correct action: **3 / 3** (held)
  - Median `"Not me"` tap -> first assistant audio: **0.611s** (improved from `0.798s`, `-0.187s` — fastest 10-run median yet; range `0.531s–0.947s`)
  - Median end of caller speech -> first assistant audio: **1.704s** (improved from `1.873s`, `-0.169s`, and faster than M4 `1.725s`)
- **Decision:** Every metric held or improved (`10/10`, `3/3`, `0.611s` tap->voice, `1.704s` speech->voice), single history row, and fast Gemini 4 Carbon report on `/senior` & `/family`; committed as `m6-iter6`.
