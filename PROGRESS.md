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
