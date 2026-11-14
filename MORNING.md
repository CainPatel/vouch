# Vouch — Morning Handoff for Cain

## Current Build Status (Updated at Milestone M4)
- **Cloud Run Deploy Commands** (`gcloud` is not installed on this Mac; run these 3 commands to deploy):
  ```bash
  gcloud config set project YOUR_GCP_PROJECT_ID
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
  GEMINI_API_KEY="$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2-)" bash scripts/deploy.sh
  ```
- **Live Two-Way Audio Status:** SHIPPED & VERIFIED (`gemini-3.8-live` real bidirectional PCM audio via browser `AudioWorklet`s + `gemini-4-carbon` post-call family report + `gemini-3.8-flash-tts` stock caller clips).
- **10-Run Hero Fake-Mic Reliability:** **10 / 10 consecutive passes (100%)**
  - Median `"Not me" tap -> first assistant audio`: **0.782s** (target < 1.5s)
  - Median `end of caller speech -> first assistant audio`: **1.725s**
  - Scripted scenarios passing: **3 / 3** (Grandson bail scam, Bank fraud scam, Elm Street Pharmacy legit)

---

## Local Quickstart
```bash
make run
# Open http://localhost:8080/demo
```

## Pre-Recording Manual Checks
1. **Headphones:** Wear headphones on the laptop running `/demo` so the open mic doesn't pick up the speaker.
2. **Mic Permission:** Allow microphone access when clicking **Call Ruth** on `/demo` (use `http://localhost:8080/demo` locally, not `127.0.0.1`).
3. **Second Device (Jake's Phone):** Scan the QR code on `/demo` once deployed to Cloud Run HTTPS so you can tap **Not me** on a real phone on camera.

## Note on Gemini 4 Carbon
`gemini-4-carbon` IS live on your `GEMINI_API_KEY` and generates the post-call family report automatically after every call.
