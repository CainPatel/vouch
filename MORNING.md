# Vouch — Morning Handoff for Cain

## Current Build Status (Updated at Milestone M1)
- **Cloud Run Deploy Commands** (`gcloud` is not installed on this Mac; run these 3 commands to deploy):
  ```bash
  gcloud config set project YOUR_GCP_PROJECT_ID
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
  GEMINI_API_KEY="$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2-)" bash scripts/deploy.sh
  ```
- **Live Two-Way Audio Status:** In progress (M0 & M1 complete; M2 Live API session & M3 browser audio next). Models confirmed on your `.env` key: `gemini-3.8-live` (`bidiGenerateContent`), `gemini-4-carbon` (`Gemini 4 Carbon`), and `gemini-3.8-flash-tts`.
- **10-Run Hero Fake-Mic Reliability:** Pending M4.

---

## Local Quickstart
```bash
make run
# Open http://localhost:8080/demo
```

## Pre-Recording Manual Checks
1. **Headphones:** Wear headphones on the laptop running `/demo` so the open mic doesn't pick up the speaker.
2. **Mic Permission:** Allow microphone access when clicking **Call Ruth** on `/demo`.
3. **Second Device (Jake's Phone):** Scan the QR code on `/demo` (once deployed to Cloud Run HTTPS, or on the same Wi-Fi LAN via `http://<mac-lan-ip>:8080/family?room=CODE`) so you can tap **Not me** on a real phone on camera.

## Note on Gemini 4 Carbon
`gemini-4-carbon` IS already live on your `GEMINI_API_KEY` and auto-selected for the post-call family report (`VOUCH_REPORT_MODEL` overrides it if ever needed).

*(This file is updated automatically at every milestone.)*
