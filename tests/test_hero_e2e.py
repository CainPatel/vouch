from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
GRANDSON_CLIP = ROOT_DIR / "static" / "audio" / "grandson_bail.wav"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_server_url() -> str:
    external_url = os.getenv("VOUCH_E2E_URL", "").strip()
    if external_url:
        yield external_url.rstrip("/")
        return

    port = _free_port()
    env = os.environ.copy()
    env["VOUCH_MOCK"] = "0"
    env["VOUCH_TEST_MODE"] = "1"
    env["PORT"] = str(port)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://localhost:{port}"
    deadline = time.time() + 15.0
    import urllib.request

    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=1.5) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.2)

    if not ready:
        proc.terminate()
        out, _ = proc.communicate(timeout=3)
        raise RuntimeError(f"Server failed to start:\n{out}")

    try:
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_single_hero_fake_mic(base_url: str, record_video_dir: Path | None = None) -> dict:
    assert GRANDSON_CLIP.exists(), f"Missing clip: {GRANDSON_CLIP}"
    clip_arg = str(GRANDSON_CLIP.resolve())

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={clip_arg}",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        ctx_kwargs: dict = {
            "viewport": {"width": 1920, "height": 1080},
            "permissions": ["microphone"],
        }
        if record_video_dir:
            record_video_dir.mkdir(parents=True, exist_ok=True)
            ctx_kwargs["record_video_dir"] = str(record_video_dir)
            ctx_kwargs["record_video_size"] = {"width": 1920, "height": 1080}

        context = browser.new_context(**ctx_kwargs)

        try:
            # 1. Open /demo (creates room)
            demo_page = context.new_page()
            demo_Metrics: list[dict] = []
            demo_page.on(
                "websocket",
                lambda ws: ws.on(
                    "framereceived",
                    lambda payload: _capture_ws_metrics(payload, demo_Metrics),
                ),
            )
            demo_page.goto(f"{base_url}/demo", wait_until="domcontentloaded")
            demo_page.wait_for_url("**/demo?room=**", timeout=10000)
            parsed = urlparse(demo_page.url)
            room = parse_qs(parsed.query)["room"][0]

            # 2. Also open /caller?room=CODE in dedicated tab (drives fake-mic -> worklet -> server -> Live)
            caller_page = context.new_page()
            caller_page.goto(
                f"{base_url}/caller?room={room}", wait_until="networkidle"
            )

            # Start the live call (uses fake mic with grandson_bail.wav)
            caller_page.get_by_test_id("call-ruth-btn").click()

            # 3. Wait for family verification card inside /demo's familyFrame
            family_frame = demo_page.frame_locator("#familyFrame")
            senior_frame = demo_page.frame_locator("#seniorFrame")

            not_me_btn = family_frame.get_by_test_id("btn-not-me")
            not_me_btn.wait_for(state="visible", timeout=25000)

            claimed_name = (
                family_frame.get_by_test_id("verify-claimed-name")
                .inner_text()
                .strip()
            )
            assert "jake" in claimed_name.lower(), f"Expected Jake in verification card, got {claimed_name}"

            # Give pre-tap assistant hold audio a moment (~1.0s) to finish playing naturally before tapping Not me
            demo_page.wait_for_timeout(1100)

            # 4. Tap "Not me"
            t_tap = time.time()
            not_me_btn.click()

            # 5. Wait for Ruth's senior frame to show Blocked verdict AND caller audio to play > 1.0s post-tap
            senior_headline = senior_frame.get_by_test_id("senior-headline")
            deadline = time.time() + 22.0
            verdict_text = ""
            stats = {}
            while time.time() < deadline:
                verdict_text = senior_headline.inner_text()
                stats = caller_page.evaluate("() => window.__vouchAudioStats || {}")
                if (
                    "blocked:" in verdict_text.lower()
                    and stats.get("postTapPlayedSeconds", 0) > 1.0
                ):
                    break
                demo_page.wait_for_timeout(150)

            # Wait up to 3s for call_ended metrics event to arrive
            end_wait = time.time() + 4.0
            while time.time() < end_wait and not any(
                m.get("type") == "call_ended" for m in demo_Metrics
            ):
                demo_page.wait_for_timeout(150)

            caller_transcript_text = (
                caller_page.get_by_test_id("caller-transcript").inner_text().lower()
            )

            assert any(
                k in caller_transcript_text for k in ("bail", "jake")
            ), f"Caller transcript missing 'bail'/'Jake': {caller_transcript_text}"
            assert "blocked:" in verdict_text.lower(), f"Senior page missing Blocked verdict: {verdict_text}"
            assert "jake" in verdict_text.lower(), f"Senior verdict missing Jake: {verdict_text}"

            post_tap_played = float(stats.get("postTapPlayedSeconds", 0))
            assert post_tap_played > 1.0, (
                f"Expected >1.0s of assistant audio played after tap, got {stats}"
            )

            # If running against local test-mode server, check captured assistant transcript file
            if not os.getenv("VOUCH_E2E_URL"):
                latest_txt = ARTIFACTS_DIR / "latest_transcript.txt"
                if latest_txt.exists():
                    txt_content = latest_txt.read_text(encoding="utf-8").lower()
                    assert any(
                        p in txt_content
                        for p in ("isn't calling", "is not calling", "not calling", "wasn't calling", "goodbye")
                    ), f"Artifact transcript missing denial: {txt_content}"

            end_events = [m for m in demo_Metrics if m.get("type") == "call_ended"]
            metrics = end_events[-1].get("metrics", {}) if end_events else {}

            return {
                "room": room,
                "claimed_name": claimed_name,
                "verdict_text": verdict_text,
                "post_tap_played_s": round(post_tap_played, 2),
                "speech_to_first_audio_s": metrics.get("speech_to_first_audio_s"),
                "tap_to_first_audio_s": metrics.get("tap_to_first_audio_s"),
                "total_elapsed_s": round(time.time() - t_tap, 2),
            }
        finally:
            context.close()
            browser.close()


def _capture_ws_metrics(payload: str | bytes, sink: list[dict]) -> None:
    if not isinstance(payload, str):
        return
    import json

    try:
        obj = json.loads(payload)
        if obj.get("type") in ("call_ended", "verification_requested", "call_blocked"):
            sink.append(obj)
    except Exception:
        pass


def test_hero_fake_mic_once(live_server_url: str):
    res = run_single_hero_fake_mic(live_server_url)
    print("HERO E2E RESULT:", res)
