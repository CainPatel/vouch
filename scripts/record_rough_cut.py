from __future__ import annotations

import shutil
import struct
import sys
import time
import wave
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from playwright.sync_api import sync_playwright
from scripts.run_eval import start_local_server

ARTIFACTS_DIR = ROOT_DIR / "artifacts"
GRANDSON_CLIP = ROOT_DIR / "static" / "audio" / "grandson_bail.wav"


def _read_wav_24k_int16(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    samples = memoryview(raw).cast("h")
    mono = [samples[i] for i in range(0, len(samples), nch)] if nch > 1 else list(samples)
    if sr == 24000:
        return mono
    ratio = sr / 24000.0
    out_len = int(len(mono) / ratio)
    return [mono[min(len(mono) - 1, int(i * ratio))] for i in range(out_len)]


def main() -> None:
    tmp_vid_dir = ROOT_DIR / ".tmp" / "rough_cut_video"
    if tmp_vid_dir.exists():
        shutil.rmtree(tmp_vid_dir)
    tmp_vid_dir.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    proc, base_url = start_local_server()
    assistant_packets: list[tuple[float, bytes]] = []
    call_start_offset: float | None = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-audio-capture={GRANDSON_CLIP.resolve()}",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                permissions=["microphone"],
                record_video_dir=str(tmp_vid_dir),
                record_video_size={"width": 1920, "height": 1080},
            )

            video_t0 = time.time()
            page = context.new_page()

            def on_ws(ws):
                def on_frame(payload):
                    nonlocal call_start_offset
                    rel_t = time.time() - video_t0
                    if isinstance(payload, bytes):
                        assistant_packets.append((rel_t, payload))
                    elif isinstance(payload, str) and '"call_started"' in payload:
                        if call_start_offset is None:
                            call_start_offset = rel_t

                ws.on("framereceived", on_frame)

            page.on("websocket", on_ws)
            page.goto(f"{base_url}/demo", wait_until="networkidle")

            # Inject burned-in cinema caption banner at bottom-center driven by live transcript events
            page.evaluate(
                """() => {
                const banner = document.createElement('div');
                banner.id = 'burnedCaptionOverlay';
                Object.assign(banner.style, {
                    position: 'fixed',
                    bottom: '76px',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    maxWidth: '1320px',
                    padding: '10px 22px',
                    borderRadius: '12px',
                    background: 'rgba(5, 8, 17, 0.88)',
                    border: '1px solid rgba(148, 163, 184, 0.35)',
                    color: '#f8fafc',
                    fontSize: '22px',
                    fontWeight: '700',
                    textAlign: 'center',
                    zIndex: '9000',
                    boxShadow: '0 12px 32px rgba(0,0,0,0.6)',
                    display: 'none',
                });
                document.body.appendChild(banner);

                const cText = document.getElementById('callerCaptionText');
                const aText = document.getElementById('assistantCaptionText');
                const obs = new MutationObserver(() => {
                    banner.style.display = 'block';
                });
                if (cText) {
                    new MutationObserver(() => {
                        banner.style.display = 'block';
                        banner.innerHTML = '<span style="color:#38bdf8">[Caller]</span> ' + cText.textContent;
                    }).observe(cText, { childList: true, characterData: true, subtree: true });
                }
                if (aText) {
                    new MutationObserver(() => {
                        banner.style.display = 'block';
                        banner.innerHTML = '<span style="color:#4ade80">[Vouch Assistant]</span> ' + aText.textContent;
                    }).observe(aText, { childList: true, characterData: true, subtree: true });
                }
            }"""
            )

            page.wait_for_timeout(800)

            caller_f = page.frame_locator("#callerFrame")
            family_f = page.frame_locator("#familyFrame")
            senior_f = page.frame_locator("#seniorFrame")

            # Start call directly inside /demo's Caller phone frame
            caller_f.get_by_test_id("call-ruth-btn").click()

            not_me = family_f.get_by_test_id("btn-not-me")
            not_me.wait_for(state="visible", timeout=25000)
            page.wait_for_timeout(1400)
            not_me.click()

            # Wait for Blocked verdict AND Gemini 4 Carbon report card so viewers see the complete flow
            deadline = time.time() + 20.0
            while time.time() < deadline:
                hl = senior_f.get_by_test_id("senior-headline").inner_text().lower()
                if "blocked:" in hl and senior_f.get_by_test_id("senior-carbon-report").is_visible():
                    break
                page.wait_for_timeout(250)

            # Hold final frame for 2.2s so viewer can read Blocked verdict & Carbon report
            page.wait_for_timeout(2200)
            total_video_s = time.time() - video_t0

            vid = page.video
            context.close()
            raw_webm_path = Path(vid.path())
            browser.close()

        target_webm = tmp_vid_dir / "raw_demo.webm"
        shutil.copy2(raw_webm_path, target_webm)

        # Build sample-accurate 24kHz mono WAV mix of caller clip + assistant audio chunks
        sr = 24000
        total_samples = int((total_video_s + 1.0) * sr)
        mix = [0] * total_samples

        caller_samples = _read_wav_24k_int16(GRANDSON_CLIP)
        c_start = int((call_start_offset or 1.0) * sr)
        for idx, s in enumerate(caller_samples):
            pos = c_start + idx
            if 0 <= pos < total_samples:
                mix[pos] = max(-32768, min(32767, mix[pos] + int(s * 0.9)))

        playhead = 0
        for rel_t, chunk in assistant_packets:
            samples = memoryview(chunk[: len(chunk) & ~1]).cast("h")
            start_idx = max(playhead, int(rel_t * sr))
            for idx, s in enumerate(samples):
                pos = start_idx + idx
                if 0 <= pos < total_samples:
                    mix[pos] = max(-32768, min(32767, mix[pos] + int(s)))
            playhead = start_idx + len(samples)

        wav_out = tmp_vid_dir / "mixed_audio.wav"
        with wave.open(str(wav_out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(mix)}h", *mix))

        print(
            f"[rough_cut] Recorded {total_video_s:.2f}s video + {len(assistant_packets)} assistant packets -> {target_webm}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
