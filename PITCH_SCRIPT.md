# Vouch — 2-Minute Team Intro & Elevator Pitch Script (`PITCH_SCRIPT.md`)

**Target runtime:** 1 minute 50 seconds – 2 minutes 00 seconds.

---

## 0:00 – 0:22 · Team Intro
`[TEAM INTRO — Cain fills in: Hi, I'm Cain Patel, ... (your background, why protecting family / building real-time voice AI matters to you, and what you built solo/with your team at the Berkeley x DeepMind Hackathon).]`

---

## 0:22 – 0:48 · The Problem & Why Existing Tools Fail
Every day, older adults get a phone call that sounds exactly like a panicked grandchild in jail needing bail money, or a bank's fraud department warning that their life savings are being drained right now.

According to the FTC, reports of older adults losing over $100,000 to impersonation scammers jumped eightfold between 2020 and 2024, and the FBI's IC3 Elder Fraud reports now track billions of dollars in annual losses for Americans over 60.

Spam filters and blocklists fail here because scammers spoof fresh local numbers on every call — and once a senior hears a panicked voice begging *"Please don't tell Mom"*, fear hijacks judgment before anyone else knows the call happened.

---

## 0:48 – 1:18 · The Product: Vouch
**Vouch** is an AI call screener that answers unknown numbers for older adults *before* their phone ever rings.

1. **Routine callers get right through:** When Elm Street Pharmacy calls about a prescription, Vouch verifies it's ordinary business and rings Ruth's phone with a one-line summary.
2. **Institution claims are stopped cold:** Anyone claiming to be a bank, government agency, or tech support is never connected — Ruth simply gets a calm note to call the number on the back of her card if needed.
3. **Family claims are verified out-of-band in real time:** When a caller claims *"Grandma, it's Jake, I need $4,000 for bail"*, **Gemini 3.8 Live** holds the caller in natural voice conversation and pings the *real* Jake's phone. Jake taps **Not me**, Gemini says *"Jake says he isn't calling. Goodbye"*, ends the call, and **Gemini 4 Carbon** writes a concise security brief for the whole family.

Notice why this defeats AI voice cloning completely: Vouch doesn't try to guess whether audio waveforms are synthetic — it verifies *intent* out-of-band with the real person in one tap.

---

## 1:18 – 1:38 · Why Now & Why Gemini
Until sub-second native audio models with real-time tool calling existed, an AI call screener sounded like a laggy robotic phone tree that legitimate callers hung up on. **Gemini 3.8 Live** handles bidirectional voice and mid-call verification responses in under a second, while **Gemini 4 Carbon** analyzes the full call transcript afterward to classify subtle social-engineering patterns for the family.

---

## 1:38 – 2:00 · Buyer, Business Model & Expansion
- **Who buys first (B2C Family Plan):** Adult children in the sandwich generation pay **$12/month** to protect their parents' phone lines via simple conditional call forwarding — zero new hardware and zero apps for the senior to learn.
- **Institutional B2B2C distribution:** Regional banks, credit unions, wireless carriers, and Medicare Advantage plans sponsor Vouch for older members to prevent catastrophic authorized-push-payment wire losses.
- **Expansion:** From voice calls into SMS/email scam triage, high-risk wire/payment-moment verification, and executive deepfake wire-fraud defense for small businesses.

With Vouch, scammers talk to Gemini — and families stay one tap ahead. Thank you.
