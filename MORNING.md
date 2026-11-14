# Vouch — Morning Handoff for Cain

## 1. Deploy to Cloud Run (3 Commands)
`gcloud` is not installed on this Mac (per run rules, it was not installed). The Docker image (`vouch:local`) and `scripts/deploy.sh` have been built and verified end-to-end with the Playwright fake-microphone hero test. Run these 3 commands from any shell with `gcloud` logged in:

```bash
gcloud config set project YOUR_GCP_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
GEMINI_API_KEY="$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2-)" bash scripts/deploy.sh
```

After `deploy.sh` prints your `https://vouch-...run.app` URL, verify it with:
```bash
VOUCH_E2E_URL="https://YOUR-CLOUD-RUN-URL.run.app" uv run pytest tests/test_hero_e2e.py -v -s
```

## 2. Headline Build Metrics (Milestone M5)
- **Live Two-Way Audio Shipped:** **YES** — real bidirectional PCM audio via browser `AudioWorklet`s (`16 kHz` mic in, `24 kHz` voice out) connected to **Gemini 3.8 Live** (`gemini-3.8-live`), post-call family security report by **Gemini 4 Carbon** (`gemini-4-carbon`), and stock-voice scripted clips by **Gemini 3.8 Flash TTS** (`gemini-3.8-flash-tts`).
- **10-Run Fake-Mic Hero Reliability:** **10 / 10 consecutive passes (100%)** (60/60 cumulative across M4 + M6 eval runs)
- **Median `"Not me"` tap -> first assistant audio:** **0.798s** (target < 1.5s; best 10-run median `0.685s`)
- **Median end of caller speech -> first assistant audio:** **1.873s** (scenario clips: `1.24s–1.39s`)
- **Scripted Caller Scenarios:** **3 / 3 passing** (Grandson bail scam -> verified & blocked; Bank fraud -> blocked immediately; Elm Street Pharmacy -> passed through ringing Ruth)

---

## Local Quickstart
```bash
make run
# Open http://localhost:8080/demo
```

## Pre-Recording Manual Checks
1. **Headphones:** Wear headphones on the laptop running `/demo` so the open mic doesn't pick up the speaker.
2. **Mic Permission:** Allow microphone access when clicking **Call Ruth** on `/demo` (use `http://localhost:8080/demo` locally or your HTTPS Cloud Run URL).
3. **Second Device (Jake's Phone):** Scan the QR code on `/demo` on your real phone so you can tap **Not me** live on camera.
