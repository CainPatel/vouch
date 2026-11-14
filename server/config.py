from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import certifi
from dotenv import load_dotenv

# Ensure Python SSL connections (httpx/websockets) use valid CA bundle on macOS & Linux
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

ROOT_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
PROMPTS_DIR = SERVER_DIR / "prompts"

load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger("vouch.config")


def is_mock_mode() -> bool:
    return os.getenv("VOUCH_MOCK", "0").strip().lower() in ("1", "true", "yes")


def is_test_mode() -> bool:
    return os.getenv("VOUCH_TEST_MODE", "0").strip().lower() in ("1", "true", "yes")


def load_contacts() -> dict:
    with open(SERVER_DIR / "contacts.json", encoding="utf-8") as f:
        return json.load(f)


def load_screener_prompt() -> str:
    prompt_text = (PROMPTS_DIR / "screener.md").read_text(encoding="utf-8")
    contacts = load_contacts()
    family_desc = ", ".join(
        f"{m['name']} ({m['relationship']})" for m in contacts.get("family", [])
    )
    return (
        f"{prompt_text}\n\n"
        f"## Private Contact Directory (NEVER reveal these names to an unverified caller)\n"
        f"- Protected senior: {contacts['senior']['name']}\n"
        f"- Verified family contacts on file for out-of-band ping: {family_desc}\n"
    )


@dataclass
class ResolvedModels:
    live_model: str
    live_fallbacks: list[str]
    report_model: str
    report_label: str
    tts_model: str


_RESOLVED_MODELS: ResolvedModels | None = None


def _strip_prefix(name: str) -> str:
    return name[7:] if name.startswith("models/") else name


def discover_models(force_refresh: bool = False) -> ResolvedModels:
    """List models available to GEMINI_API_KEY at runtime per SPEC section 3."""
    global _RESOLVED_MODELS
    if _RESOLVED_MODELS is not None and not force_refresh:
        return _RESOLVED_MODELS

    live_override = os.getenv("VOUCH_LIVE_MODEL", "").strip()
    report_override = os.getenv("VOUCH_REPORT_MODEL", "").strip()
    tts_override = os.getenv("VOUCH_TTS_MODEL", "").strip()

    if is_mock_mode():
        _RESOLVED_MODELS = ResolvedModels(
            live_model=live_override or "mock-live",
            live_fallbacks=[],
            report_model=report_override or "mock-carbon",
            report_label="Mock Gemini 4 Carbon",
            tts_model=tts_override or "mock-tts",
        )
        return _RESOLVED_MODELS

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    live_candidates: list[str] = []
    generate_models: dict[str, str] = {}  # id -> display_name

    if api_key:
        try:
            from google import genai

            client = genai.Client(
                api_key=api_key, http_options={"api_version": "v1beta"}
            )
            for m in client.models.list():
                mid = _strip_prefix(m.name or "")
                disp = getattr(m, "display_name", None) or mid
                actions = list(getattr(m, "supported_actions", None) or [])
                if "bidiGenerateContent" in actions:
                    # Exclude specialized non-dialogue models (transcribe-only, translate-only, robotics)
                    if not any(
                        skip in mid
                        for skip in ("transcribe", "translate", "robotics", "lyria")
                    ):
                        live_candidates.append(mid)
                if "generateContent" in actions:
                    generate_models[mid] = disp
        except Exception as exc:
            logger.warning("Model listing failed, falling back to defaults: %s", exc)

    # 1. Pick Live model: prefer gemini-3.8-live, then *-live*, then *native-audio*
    preferred_live_order = [
        "gemini-3.8-live",
        "gemini-3.1-flash-live-preview",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-2.5-flash-native-audio-preview-12-2025",
        "gemini-3.8-live-extended-thinking",
    ]
    ordered_live: list[str] = []
    for pref in preferred_live_order:
        if pref in live_candidates and pref not in ordered_live:
            ordered_live.append(pref)
    for cand in live_candidates:
        if ("live" in cand or "native-audio" in cand) and cand not in ordered_live:
            ordered_live.append(cand)
    if not ordered_live:
        ordered_live = ["gemini-3.8-live"]

    chosen_live = _strip_prefix(live_override) if live_override else ordered_live[0]
    fallbacks = [m for m in ordered_live if m != chosen_live]

    # 2. Pick post-call report model: prefer Carbon, else strongest Gemini model
    chosen_report = ""
    report_label = "Gemini 4 Carbon"
    if report_override:
        chosen_report = _strip_prefix(report_override)
        report_label = generate_models.get(chosen_report, chosen_report)
    else:
        carbon_ids = [mid for mid in generate_models if "carbon" in mid.lower()]
        if "gemini-4-carbon" in carbon_ids:
            chosen_report = "gemini-4-carbon"
            report_label = generate_models.get("gemini-4-carbon", "Gemini 4 Carbon")
        elif carbon_ids:
            chosen_report = carbon_ids[0]
            report_label = generate_models.get(chosen_report, chosen_report)
        else:
            for fallback_id in (
                "gemini-4-argon",
                "gemini-3.1-pro-preview",
                "gemini-3.8-flash",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
            ):
                if fallback_id in generate_models:
                    chosen_report = fallback_id
                    report_label = generate_models[fallback_id]
                    break
            if not chosen_report:
                chosen_report = "gemini-4-carbon"
                report_label = "Gemini 4 Carbon"

    # 3. Pick TTS model
    if tts_override:
        chosen_tts = _strip_prefix(tts_override)
    elif "gemini-3.8-flash-tts" in generate_models:
        chosen_tts = "gemini-3.8-flash-tts"
    elif "gemini-3.8-flash-lite-tts" in generate_models:
        chosen_tts = "gemini-3.8-flash-lite-tts"
    else:
        chosen_tts = "gemini-3.8-flash-tts"

    _RESOLVED_MODELS = ResolvedModels(
        live_model=chosen_live,
        live_fallbacks=fallbacks,
        report_model=chosen_report,
        report_label=report_label,
        tts_model=chosen_tts,
    )
    logger.info(
        "Resolved Gemini models: live=%s (fallbacks=%s), report=%s (%s), tts=%s",
        _RESOLVED_MODELS.live_model,
        _RESOLVED_MODELS.live_fallbacks,
        _RESOLVED_MODELS.report_model,
        _RESOLVED_MODELS.report_label,
        _RESOLVED_MODELS.tts_model,
    )
    return _RESOLVED_MODELS
