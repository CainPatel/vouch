from __future__ import annotations

import asyncio
import os
import struct
import sys
import time
import wave
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

os.environ["VOUCH_MOCK"] = "0"
os.environ["VOUCH_TEST_MODE"] = "1"

from server.config import STATIC_DIR, discover_models
from server.hub import RoomHub
from server.models import CallState


def load_wav_as_16k_pcm(wav_path: Path) -> bytes:
    with wave.open(str(wav_path), "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if sw != 2:
        raise ValueError(f"Expected 16-bit WAV, got sampwidth={sw}")

    samples = memoryview(raw).cast("h")
    if nch > 1:
        mono = [samples[i] for i in range(0, len(samples), nch)]
    else:
        mono = list(samples)

    if sr == 16000:
        out_samples = mono
    else:
        ratio = sr / 16000.0
        out_len = int(len(mono) / ratio)
        out_samples = [mono[min(len(mono) - 1, int(i * ratio))] for i in range(out_len)]

    return struct.pack(f"<{len(out_samples)}h", *out_samples)


async def run_smoke() -> None:
    models = discover_models(force_refresh=True)
    print(f"[smoke] Live model: {models.live_model} | Report model: {models.report_model}")

    clip_path = STATIC_DIR / "audio" / "grandson_bail.wav"
    if not clip_path.exists():
        raise FileNotFoundError(f"Missing {clip_path}; run `make clips` first.")

    pcm16k = load_wav_as_16k_pcm(clip_path)
    print(f"[smoke] Loaded {clip_path.name} -> {len(pcm16k)} bytes @ 16kHz ({len(pcm16k)/32000:.2f}s)")

    hub = RoomHub()
    ctrl = await hub.start_call("SMOKE1")
    room = ctrl.room

    # Task to stream 60ms (1920-byte) audio frames + trailing silence until call ends
    async def stream_audio():
        frame_bytes = 1920  # 60ms at 16kHz 16-bit mono
        offset = 0
        while offset < len(pcm16k) and not ctrl._closed:
            chunk = pcm16k[offset : offset + frame_bytes]
            offset += frame_bytes
            await ctrl.handle_caller_audio(chunk)
            await asyncio.sleep(0.055)
        ctrl.mark_caller_speech_end()
        silence = b"\x00" * frame_bytes
        while not ctrl._closed:
            await ctrl.handle_caller_audio(silence)
            await asyncio.sleep(0.06)

    stream_task = asyncio.create_task(stream_audio())

    try:
        # 1. Wait for verification_requested tool call
        t0 = time.time()
        while room.verification is None:
            if time.time() - t0 > 20.0:
                raise TimeoutError(
                    f"Timed out waiting for request_family_verification. Transcripts so far: {[t.to_dict() for t in room.transcripts]}"
                )
            await asyncio.sleep(0.1)

        ver = room.verification
        print(f"[smoke] Tool called: request_family_verification({ver.to_dict()})")
        assert "jake" in ver.claimed_name.lower(), f"Unexpected claimed_name: {ver.claimed_name}"

        # Allow assistant's pre-tap hold line ("One moment while I confirm with Jake") to stream
        pre_tap_wait = time.time()
        while sum(len(c) for c in ctrl._test_audio_chunks) < 24000 and (time.time() - pre_tap_wait) < 8.0:
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.8)
        pre_tap_audio_bytes = sum(len(c) for c in ctrl._test_audio_chunks)
        print(f"[smoke] Pre-tap assistant audio received: {pre_tap_audio_bytes / 48000:.2f}s")
        assert pre_tap_audio_bytes > 4800, "Expected pre-tap assistant hold audio!"

        # 2. Simulate Jake tapping "Not me"
        print("[smoke] Submitting family verification answer: 'denied' ('Not me')...")
        await ctrl.submit_verification_answer(ver.id, "denied")

        # 3. Wait for call to end cleanly with blocked verdict and post-tap audio
        t_tap = time.time()
        while not ctrl._closed:
            if time.time() - t_tap > 20.0:
                raise TimeoutError("Timed out waiting for post-tap denial speech and call completion")
            await asyncio.sleep(0.1)

    finally:
        stream_task.cancel()
        if not ctrl._closed:
            await ctrl.end_call()

    caller_text = " ".join(t.text for t in room.transcripts if t.speaker == "caller")
    assistant_text = " ".join(t.text for t in room.transcripts if t.speaker == "assistant")
    post_tap_audio_s = ctrl._assistant_audio_bytes_post_tap / 48000.0
    metrics = room.metrics.to_dict()

    print("\n=== SMOKE TEST RESULTS ===")
    for t in room.transcripts:
        print(f"  [{t.speaker.upper()}] {t.text}")
    print(f"  Verdict: {room.last_verdict}")
    print(f"  Post-tap assistant audio: {post_tap_audio_s:.2f}s")
    print(f"  Latency metrics: {metrics}")

    assert any(w in caller_text.lower() for w in ("jake", "bail")), f"Caller transcript missing expected words: {caller_text}"
    assert room.last_verdict and room.last_verdict["outcome"] == "blocked", f"Expected blocked verdict, got {room.last_verdict}"
    assert post_tap_audio_s >= 1.0, f"Expected >1.0s post-tap assistant audio, got {post_tap_audio_s:.2f}s"
    lower_asst = assistant_text.lower()
    assert any(
        phrase in lower_asst
        for phrase in ("isn't calling", "is not calling", "not calling", "wasn't calling", "goodbye")
    ), f"Assistant transcript missing denial phrase: {assistant_text}"
    print("[smoke] PASS!")


if __name__ == "__main__":
    asyncio.run(run_smoke())
