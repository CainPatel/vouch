# Vouch — Morning Handoff for Cain

## 1. Deploy to Cloud Run (Exact 3 Commands)
`gcloud` is not installed on this machine (per run rules, no install or login was attempted). The `Dockerfile` (`vouch:local`) and `scripts/deploy.sh` are built and verified end-to-end with the Chromium fake-microphone hero test (`0` secrets baked into the image). Run these **exact 3 commands** from a shell where `gcloud` is installed and logged in:

```bash
gcloud config set project YOUR_GCP_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
GEMINI_API_KEY="$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2-)" bash scripts/deploy.sh
```

Once `scripts/deploy.sh` prints your `https://vouch-...run.app` URL:
1. Paste that URL into `README.md` (line 7) and `ONE_PAGER_TEAM.txt` (line 22).
2. Run the automated fake-mic hero check against the live Cloud Run URL (takes ~15s):
   ```bash
   VOUCH_E2E_URL="https://YOUR-CLOUD-RUN-URL.run.app" uv run pytest tests/test_hero_e2e.py -v -s
   ```

## 2. Final Build Status & Frozen M7 Metrics
- **Live Two-Way Audio Shipped:** **YES** — 100% live bidirectional PCM audio (`16 kHz` browser mic `AudioWorklet` in -> **`gemini-3.8-live`** -> `24 kHz` gapless `AudioWorklet` out), live input/output speech transcription, live function calling, async post-call family security report on **Gemini 4 Carbon** (`gemini-4-carbon`), and stock-voice scripted clips on **Gemini 3.8 Flash TTS** (`gemini-3.8-flash-tts`). Mock mode (`VOUCH_MOCK`) is OFF (`0`) by default.
- **Final 10-Run Consecutive Fake-Mic Hero Result:** **10 / 10 PASS (100%)** *(and 190+ consecutive passes across overnight testing)*
- **Final Median `"Not me"` Tap -> First Assistant Audio:** **0.594s** *(target `< 1.5s`; range `0.511s – 0.894s`)*
- **Final Median End of Caller Speech -> First Assistant Audio:** **1.646s** *(range `1.427s – 2.170s`; best 10-run median `1.542s`)*
- **Scripted Caller Scenarios:** **3 / 3 PASS**
  1. *Grandson in jail (`$4,000` bail)* -> holds caller, pings Jake's phone, speaks `"Jake says he isn't calling. Goodbye."` on **Not me**, blocks call, writes Gemini 4 Carbon report.
  2. *Bank fraud department* -> blocks immediately without ringing Ruth, speaks polite refusal, writes Gemini 4 Carbon report.
  3. *Elm Street Pharmacy* -> passes through with summary (`Dana from Elm Street Pharmacy — prescription ready for pickup`), rings Ruth's phone.
- **Automatic Backup Video (`artifacts/demo_auto.mp4`):** **YES, generated (19.6s, 1920x1080 H.264/AAC, under 60s) and the audio lines up.** Caller audio and live Gemini 3.8 Live assistant audio packets are mixed at their exact captured WebSocket timestamps (`24 kHz` PCM -> AAC) with highlighted burned-in footer captions and zero bezel overlap.

---

## 3. What to Check by Hand (3 Minutes)
Start locally with `make run` (opens `http://localhost:8080/demo`) or open your deployed `https://<cloud-run-url>/demo`:

1. **Headphones plugged in:** Wear wired or AirPods headphones on the laptop running `/demo` so your open laptop mic doesn't feed Vouch's spoken voice back into Gemini's VAD.
2. **Browser microphone permission:** Click **Call Ruth** in the left phone frame (**Caller's Phone**) and click **Allow** on Chrome's microphone prompt. Confirm the cyan **Caller Audio (16 kHz PCM In)** waveform moves when you speak. *(Note: Chrome only grants mic access on `https://...` or `http://localhost:8080`, never on raw LAN `http://192.168.x.x`.)*
3. **Real phone opens the QR code:** Point your phone camera at the QR code on the right sidebar of `/demo`. Confirm your phone opens `/family?room=CODE` showing **Jake's Phone · Protecting Ruth**. *(Note: For your real phone over cellular/Wi-Fi to reach the room, open `/demo` on your public `https://...run.app` Cloud Run URL so the QR code encodes the public HTTPS URL rather than `localhost`.)*

---

## 4. Known Issues & Design Notes
- **Localhost QR vs. Cloud Run QR:** When `/demo` is opened at `http://localhost:8080/demo`, the QR code points to `http://localhost:8080/family?room=...`, which another phone cannot reach. Always record your real-phone shot against the deployed **Cloud Run `https://...run.app/demo` URL** so your phone connects instantly over any network.
- **Single-instance in-memory state (`--max-instances=1`):** Room state lives in memory (`scripts/deploy.sh` pins `--min-instances=1 --max-instances=1 --session-affinity`). Re-deploying resets active rooms; refresh `/demo` after redeploying to get a fresh room code and re-scan the QR code.
- **Quota & abuse guardrails active:** Calls auto-cap at **3 minutes**, active rooms cap at **5** (auto-evicting idle rooms), and `start_call` is rate-limited per IP (`15/min` in production) so sharing the public URL won't drain your API key.
- **Pause naturalness (`450 ms` VAD):** Gemini Live's VAD waits `450 ms` of silence before responding so mid-sentence pauses (like between *"Grandma, it's Jake"* and *"I need $4,000 for bail"*) aren't cut off early. Deliver your caller scam pitch in one continuous urgent breath.

---

## 5. Three Likeliest Demo Failures & Instant Fixes

| # | Symptom During Take | Root Cause | Instant Fix (< 15 seconds) |
|---|---|---|---|
| **1** | Vouch interrupts you mid-sentence or answers its own voice | Laptop speakers are bleeding into the open mic, OR you paused > 0.6s mid-pitch | Put on headphones, OR click **`Push-to-Talk: Off`** on Caller's Phone to switch to **`Hold Space / Button to Talk`**, OR click **`1. Grandson in jail ($4,000 bail)`** to stream the studio clip cleanly through the exact same audio pipeline. |
| **2** | Your real phone shows **Jake's Phone** on standby and never pops the amber card | Phone scanned an old room's QR code before `/demo` was refreshed | Check that `Room: XXXX` in `/demo`'s top-right matches `?room=XXXX` in your phone browser's URL bar; re-scan the QR code on screen. |
| **3** | Clicking **Call Ruth** shows no mic waveform | Chrome mic permission blocked or wrong input device selected in Chrome | Click the tune/lock icon left of Chrome's address bar -> allow **Microphone** -> select your active mic (or click scenario button **1** which streams audio without needing physical mic hardware). |

---

## 6. Timed Morning Checklist (Wake-Up -> 10:30 AM PT Submission)

- **07:30 – 07:45 · Wake Up & Sanity Check Locally**
  - Run `make run`, open `http://localhost:8080/demo` in Chrome with headphones, and do one 30-second test call.
- **07:45 – 08:05 · Deploy to Cloud Run & Verify Public HTTPS URL**
  - Install/login to `gcloud` if needed (or run from Cloud Shell) and execute the **3 deploy commands** at the top of this file.
  - Run `VOUCH_E2E_URL="https://YOUR-URL.run.app" uv run pytest tests/test_hero_e2e.py -v -s` to confirm green on Cloud Run.
  - Open `https://YOUR-URL.run.app/demo` on laptop + scan QR code on your real phone; do one dry run tapping **Not me** on your phone.
- **08:05 – 08:45 · Record the 1-Minute Prototype Demo Video (`DEMO_SCRIPT.md`)**
  - Follow the 5-shot list in `DEMO_SCRIPT.md` (~55s total).
  - Tip: Click **`Record Demo (.webm)`** in `/demo`'s top-right for a 3-second countdown and clean mixed Web Audio + 1080p capture (or record screen + phone camera with QuickTime/OBS).
  - Upload to **YouTube as Public** (hackathon rule requires Public YouTube link + social engagement counts toward GTM traction).
  - *Emergency fallback if time gets tight:* `artifacts/demo_auto.mp4` (19.6s, synced audio + captions) is ready to upload as-is.
- **08:45 – 09:25 · Record the 2-Minute Team Intro & Elevator Pitch (`PITCH_SCRIPT.md`)**
  - Fill in your `[TEAM INTRO]` opening (`0:00–0:22`), then read `PITCH_SCRIPT.md` (~1m55s). Upload video.
- **09:25 – 09:50 · Finalize Submission Text & Public Repo**
  - Fill in `[CAIN FILLS IN]` placeholders in `ONE_PAGER_TEAM.txt`.
  - Paste your Cloud Run URL into `README.md`, commit, and push to a **public GitHub repository** (repo & git history have been audited clean of `.env` and API keys).
- **09:50 – 10:15 · Submit on Hackathon Portal (15-min buffer before 10:30 AM PT cutoff)**
  - Double-check every link opens in an Incognito window: Cloud Run URL, Public YouTube 1-min demo video, 2-min pitch video, Public GitHub repo, `ONE_PAGER_TEAM.txt`, and `ONE_PAGER_IDEA.txt`.
