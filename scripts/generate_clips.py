from __future__ import annotations

import io
import os
import sys
import wave
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from google import genai
from server.config import STATIC_DIR, discover_models

AUDIO_DIR = STATIC_DIR / "audio"

CLIPS = [
    {
        "filename": "grandson_bail.wav",
        "voice": "Puck",
        "style": "urgent, nervous young adult speaking quickly on a phone call",
        "text": "Grandma, it's Jake. I'm in trouble, I need four thousand dollars for bail. Please don't tell Mom.",
    },
    {
        "filename": "bank_fraud.wav",
        "voice": "Charon",
        "style": "urgent, authoritative call-center representative",
        "text": "This is the fraud department at your bank. We've detected suspicious activity and need to move your funds to a safe account right now.",
    },
    {
        "filename": "pharmacy.wav",
        "voice": "Zephyr",
        "style": "warm, calm, polite neighborhood pharmacy staff member",
        "text": "Hi, this is Dana from Elm Street Pharmacy. Ruth's prescription is ready for pickup.",
    },
]


def _normalize_wav_with_padding(
    raw_bytes: bytes, lead_silence_s: float = 0.65, tail_silence_s: float = 2.2
) -> tuple[bytes, float]:
    """Ensure standard 16-bit mono RIFF WAV with clean leading/trailing silence for VAD & fake-mic."""
    if raw_bytes[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw_bytes), "rb") as rf:
            nch = rf.getnchannels()
            sampwidth = rf.getsampwidth()
            framerate = rf.getframerate()
            pcm = rf.readframes(rf.getnframes())
    else:
        # Raw 24kHz 16-bit mono PCM fallback
        nch = 1
        sampwidth = 2
        framerate = 24000
        pcm = raw_bytes

    lead_bytes = b"\x00" * (int(framerate * lead_silence_s) * nch * sampwidth)
    tail_bytes = b"\x00" * (int(framerate * tail_silence_s) * nch * sampwidth)
    full_pcm = lead_bytes + pcm + tail_bytes

    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(nch)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(full_pcm)

    duration_s = len(full_pcm) / (framerate * nch * sampwidth)
    return out.getvalue(), duration_s


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing in environment/.env")

    models = discover_models()
    tts_model = models.tts_model
    print(f"Generating caller clips with model={tts_model} (stock prebuilt voices)...")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

    for spec in CLIPS:
        out_path = AUDIO_DIR / spec["filename"]
        resp = client.models.generate_content(
            model=tts_model,
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": spec["text"],
                            "speech_metadata": {"style": spec["style"]},
                        }
                    ],
                }
            ],
            config={
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {"voice": spec["voice"]},
                },
            },
        )
        part = resp.candidates[0].content.parts[0]
        raw_audio = part.inline_data.data
        wav_bytes, dur = _normalize_wav_with_padding(raw_audio)
        out_path.write_bytes(wav_bytes)
        print(f"  -> Wrote {out_path.relative_to(ROOT_DIR)} ({dur:.2f}s, {len(wav_bytes)} bytes, voice={spec['voice']})")


if __name__ == "__main__":
    main()
