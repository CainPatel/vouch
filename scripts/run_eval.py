from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from playwright.sync_api import sync_playwright
from tests.test_hero_e2e import run_single_hero_fake_mic

ARTIFACTS_DIR = ROOT_DIR / "artifacts"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_local_server() -> tuple[subprocess.Popen, str]:
    port = _free_port()
    env = os.environ.copy()
    env["VOUCH_MOCK"] = "0"
    env["VOUCH_TEST_MODE"] = "1"
    env["VOUCH_RATE_LIMIT_PER_MIN"] = "60"
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
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=1.5) as r:
                if r.status == 200:
                    return proc, base_url
        except Exception:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("Failed to start local server for eval")


def run_three_scenarios(base_url: str, take_screenshots: bool = False) -> dict[str, bool]:
    results = {"grandson": False, "bank": False, "pharmacy": False}
    screenshots_dir = ARTIFACTS_DIR / "screenshots"
    if take_screenshots:
        screenshots_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )

        # 1. Grandson scenario button on /demo
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, permissions=["microphone"])
        page = ctx.new_page()
        page.goto(f"{base_url}/demo", wait_until="networkidle")
        page.wait_for_timeout(500)
        if take_screenshots:
            page.screenshot(path=str(screenshots_dir / "demo_01_idle.png"))

        caller_f = page.frame_locator("#callerFrame")
        senior_f = page.frame_locator("#seniorFrame")
        family_f = page.frame_locator("#familyFrame")

        caller_f.get_by_test_id("scenario-grandson").click()
        page.wait_for_timeout(1200)
        if take_screenshots:
            page.screenshot(path=str(screenshots_dir / "demo_02_screening.png"))

        not_me = family_f.get_by_test_id("btn-not-me")
        not_me.wait_for(state="visible", timeout=25000)
        page.wait_for_timeout(900)
        if take_screenshots:
            page.screenshot(path=str(screenshots_dir / "demo_03_verifying.png"))

        not_me.click()
        deadline = time.time() + 20.0
        while time.time() < deadline:
            hl = senior_f.get_by_test_id("senior-headline").inner_text().lower()
            if "blocked:" in hl and "jake" in hl:
                results["grandson"] = True
                break
            page.wait_for_timeout(200)

        # Wait a few seconds for Gemini 4 Carbon report card to render for screenshot
        if take_screenshots:
            rep_deadline = time.time() + 12.0
            while time.time() < rep_deadline:
                if senior_f.get_by_test_id("senior-carbon-report").is_visible():
                    break
                page.wait_for_timeout(300)
            page.screenshot(path=str(screenshots_dir / "demo_04_blocked_with_carbon_report.png"))
        ctx.close()

        # 2. Bank fraud scenario button on /demo -> Blocked without ringing Ruth
        ctx2 = browser.new_context(viewport={"width": 1920, "height": 1080}, permissions=["microphone"])
        page2 = ctx2.new_page()
        page2.goto(f"{base_url}/demo", wait_until="networkidle")
        caller_f2 = page2.frame_locator("#callerFrame")
        senior_f2 = page2.frame_locator("#seniorFrame")
        caller_f2.get_by_test_id("scenario-bank").click()

        deadline = time.time() + 25.0
        while time.time() < deadline:
            hl = senior_f2.get_by_test_id("senior-headline").inner_text().lower()
            if "blocked:" in hl:
                results["bank"] = True
                break
            page2.wait_for_timeout(200)
        if take_screenshots:
            page2.screenshot(path=str(screenshots_dir / "demo_05_bank_blocked.png"))
        ctx2.close()

        # 3. Pharmacy scenario button on /demo -> Passed through (Ringing Ruth)
        ctx3 = browser.new_context(viewport={"width": 1920, "height": 1080}, permissions=["microphone"])
        page3 = ctx3.new_page()
        page3.goto(f"{base_url}/demo", wait_until="networkidle")
        caller_f3 = page3.frame_locator("#callerFrame")
        senior_f3 = page3.frame_locator("#seniorFrame")
        caller_f3.get_by_test_id("scenario-pharmacy").click()

        deadline = time.time() + 25.0
        while time.time() < deadline:
            hl = senior_f3.get_by_test_id("senior-headline").inner_text().lower()
            pill = senior_f3.get_by_test_id("senior-state").inner_text().lower()
            if "incoming call:" in hl or "passed" in pill:
                results["pharmacy"] = True
                break
            page3.wait_for_timeout(200)
        if take_screenshots:
            page3.screenshot(path=str(screenshots_dir / "demo_06_pharmacy_passed.png"))
        ctx3.close()

        # Also capture standalone mobile viewports if requested
        if take_screenshots:
            parsed = urlparse(page.url if not page.is_closed() else f"{base_url}/demo?room=SNAP01")
            mctx = browser.new_context(viewport={"width": 390, "height": 844})
            mp = mctx.new_page()
            for name, route in [
                ("landing", "/"),
                ("caller_mobile", "/caller?room=SNAP01"),
                ("senior_mobile", "/senior?room=SNAP01"),
                ("family_mobile", "/family?room=SNAP01"),
            ]:
                mp.goto(f"{base_url}{route}", wait_until="networkidle")
                mp.wait_for_timeout(300)
                mp.screenshot(path=str(screenshots_dir / f"page_{name}.png"))
            mctx.close()

        browser.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--scenarios", action="store_true")
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--url", type=str, default="")
    args = parser.parse_args()

    proc = None
    base_url = args.url.rstrip("/") if args.url else ""
    if not base_url:
        proc, base_url = start_local_server()

    try:
        scenario_summary = None
        if args.scenarios:
            print(f"[eval] Running 3 scripted scenarios against {base_url}...")
            scenario_summary = run_three_scenarios(base_url, take_screenshots=args.screenshots)
            print(f"[eval] Scenarios result: {scenario_summary} ({sum(scenario_summary.values())}/3)")

        passes = 0
        speech_latencies: list[float] = []
        tap_latencies: list[float] = []
        run_details: list[dict] = []

        for i in range(1, args.runs + 1):
            t0 = time.time()
            try:
                res = run_single_hero_fake_mic(base_url)
                passes += 1
                s_lat = res.get("speech_to_first_audio_s")
                t_lat = res.get("tap_to_first_audio_s")
                if isinstance(s_lat, (int, float)):
                    speech_latencies.append(float(s_lat))
                if isinstance(t_lat, (int, float)):
                    tap_latencies.append(float(t_lat))
                res["ok"] = True
                res["run"] = i
                run_details.append(res)
                print(
                    f"  Run {i:02d}/{args.runs}: PASS | speech->voice={s_lat}s | tap->voice={t_lat}s | played={res['post_tap_played_s']}s ({time.time()-t0:.1f}s)"
                )
            except Exception as exc:
                err_info = {"run": i, "ok": False, "error": str(exc)}
                run_details.append(err_info)
                print(f"  Run {i:02d}/{args.runs}: FAIL | {exc}")

        med_speech = round(statistics.median(speech_latencies), 3) if speech_latencies else None
        med_tap = round(statistics.median(tap_latencies), 3) if tap_latencies else None

        summary = {
            "hero_passes": passes,
            "hero_total": args.runs,
            "median_speech_to_voice_s": med_speech,
            "median_tap_to_voice_s": med_tap,
            "scenarios": scenario_summary,
            "scenarios_passed": sum(scenario_summary.values()) if scenario_summary else None,
            "runs": run_details,
        }
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS_DIR / "eval_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        print("\n=== EVAL SUMMARY ===")
        print(json.dumps({k: v for k, v in summary.items() if k != "runs"}, indent=2))

        if passes < args.runs:
            sys.exit(1)
        if scenario_summary and sum(scenario_summary.values()) < 3:
            sys.exit(1)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
