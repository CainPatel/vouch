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
