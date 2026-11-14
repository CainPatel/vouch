# Vouch — 1-Minute Prototype Demo Video Script (`DEMO_SCRIPT.md`)

**Format:** 1080p screen recording of `/demo` on laptop (wearing headphones) + picture-in-picture or held-up real phone showing `/family?room=CODE` (opened via the QR code on `/demo`).
**Target runtime:** ~52–58 seconds (strictly under 60 seconds).

---

## Pre-Take Setup (30 seconds before hitting Record)
1. Plug in headphones on your laptop so the open mic doesn't pick up speaker audio.
2. Open your deployed `https://<your-cloud-run-url>/demo` in Chrome at 1920x1080.
3. Point your real phone camera at the QR code on the right side of `/demo` to open **Jake's Phone** (`/family?room=CODE`).
4. Click **Record Demo (.webm)** in the top-right of `/demo` (gives a `3… 2… 1…` countdown and captures tab video + mixed caller/assistant audio), or use QuickTime / OBS.

---

## Shot-by-Shot Script

### Shot 1 — Cold Open & Setup (`0:00 – 0:08`)
- **On screen:** `/demo` showing all three phone frames (**Caller**, **Ruth's Phone** in silent mode, **Jake's Phone** on standby) + hold your real phone briefly next to the screen showing the matching **Jake's Phone** page.
- **Voiceover (1 line):** *"Vouch is an AI call screener built on Gemini Live that stops family impersonation scams before an older adult's phone ever rings."*

### Shot 2 — The Scam Call Begins (`0:08 – 0:20`)
- **Action:** Click **Call Ruth** on the Caller phone frame and speak live into your laptop mic (with urgency):
- **Caller line (spoken live into mic):** *"Grandma, it's Jake. I'm in trouble, I need four thousand dollars for bail. Please don't tell Mom."*
- **On screen:** Caller cyan waveform dances live; live transcript streams word-for-word; **Ruth's Phone** stays silent and shows *"Vouch is screening an unknown caller"*.
- **Voiceover (1 line):** *(Let the live caller line play clearly — no voiceover overlap.)*

### Shot 3 — Gemini Live Holds the Caller & Pings the Real Grandson (`0:20 – 0:31`)
- **On screen & audio:** Vouch's green waveform lights up and **Gemini 3.8 Live** speaks out loud in real time:
  - **Assistant (heard out loud):** *"This is Ruth's assistant. One moment while I confirm with Jake."*
- **On your real phone (and the 3rd frame):** Full-screen amber **Urgent Identity Check** card pops up immediately: *"Someone claiming to be you is on the phone with Ruth asking for $4,000 (bail money). Is this you?"*
- **Voiceover (1 line):** *"Instead of waking Ruth, Gemini Live places the caller on hold and sends an out-of-band check to the real Jake's phone."*

### Shot 4 — One-Tap "Not me" & Instant Live Hangup (`0:31 – 0:44`)
- **Action:** On your real phone on camera, tap the big red **Not me — Block Call** button.
- **On screen & audio (under 1 second after tap):**
  - **Assistant (heard out loud):** *"Jake says he isn't calling. Goodbye."* — call disconnects automatically.
  - **Ruth's Phone** shows bright red verdict card: **"Blocked: someone impersonating Jake asked for $4,000."**
- **Voiceover (1 line):** *"One tap on 'Not me', and under a second later Gemini tells the scammer off and hangs up."*

### Shot 5 — Gemini 4 Carbon Family Security Report (`0:44 – 0:56`)
- **On screen:** A moment after hangup, the purple **Report by Gemini 4 Carbon** card appears on both Ruth's Phone and Jake's Phone summarizing the claim, the grandparent-bail scam pattern, what Vouch did, and the recommended next step.
- **Voiceover (1 line):** *"Ruth never heard the scam pitch, and Gemini 4 Carbon sends the family a plain-English security brief — while ordinary calls like the pharmacy ring right through."*

---

*(Backup option if short on time: `artifacts/demo_auto.mp4` is already pre-rendered at 1080p under 60 seconds via `bash scripts/make_demo_video.sh`.)*
