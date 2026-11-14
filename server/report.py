from __future__ import annotations

import json
import logging
import os
from typing import Any

from server.config import discover_models, is_mock_mode
from server.models import Room

logger = logging.getLogger("vouch.report")

REPORT_PROMPT_TEMPLATE = """You are writing a concise post-call security summary for an older adult ("Ruth") and her family after Vouch screened an incoming phone call from an unknown number.

Call outcome: {outcome}
Verdict summary: {verdict}
Verification details: {verification}

Call transcript:
{transcript_lines}

Return ONLY valid JSON with these exact four string keys (each 1 concise sentence, plain language, calm and specific):
{{
  "claim": "What the caller claimed and asked for",
  "pattern": "Which scam pattern it matches (or 'Legitimate routine call — no scam indicators' if legitimate)",
  "action_taken": "What Vouch did to protect Ruth",
  "next_step": "One concrete recommended next step for the family"
}}
"""


async def generate_family_report(room_snapshot_data: dict[str, Any]) -> dict[str, Any]:
    """Generate post-call family report in the background using Gemini 4 Carbon."""
    models = discover_models()
    call_id = room_snapshot_data.get("call_id") or ""
    outcome = room_snapshot_data.get("outcome") or "ended"
    verdict = room_snapshot_data.get("verdict_text") or ""
    verification = room_snapshot_data.get("verification")
    transcripts = room_snapshot_data.get("transcripts") or []

    if is_mock_mode():
        structured = _fallback_structured(outcome, verdict, verification)
        return {
            "type": "family_report",
            "call_id": call_id,
            "model": models.report_model,
            "model_label": f"Report by {models.report_label}",
            "structured": structured,
            "report_text": _format_text(structured),
        }

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        structured = _fallback_structured(outcome, verdict, verification)
        return {
            "type": "family_report",
            "call_id": call_id,
            "model": models.report_model,
            "model_label": f"Report by {models.report_label}",
            "structured": structured,
            "report_text": _format_text(structured),
        }

    transcript_lines = "\n".join(
        f"- {t['speaker'].capitalize()}: {t['text']}" for t in transcripts
    ) or "(No transcript recorded)"

    prompt = REPORT_PROMPT_TEMPLATE.format(
        outcome=outcome,
        verdict=verdict,
        verification=json.dumps(verification) if verification else "None",
        transcript_lines=transcript_lines,
    )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=api_key, http_options={"api_version": "v1beta"}
        )
        cfg_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "max_output_tokens": 1024,
        }
        if "gemini-4" in models.report_model or "gemini-3" in models.report_model:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")

        resp = await client.aio.models.generate_content(
            model=models.report_model,
            contents=prompt,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
        raw_text = (resp.text or "").strip()
        structured = json.loads(raw_text)
        for key in ("claim", "pattern", "action_taken", "next_step"):
            if key not in structured or not isinstance(structured[key], str):
                raise ValueError(f"Missing key {key}")
    except Exception as exc:
        logger.warning("Gemini report generation error (%s), using structured summary", exc)
        structured = _fallback_structured(outcome, verdict, verification)

    return {
        "type": "family_report",
        "call_id": call_id,
        "model": models.report_model,
        "model_label": f"Report by {models.report_label}",
        "structured": structured,
        "report_text": _format_text(structured),
    }


def _fallback_structured(
    outcome: str, verdict: str, verification: dict[str, Any] | None
) -> dict[str, str]:
    if outcome == "blocked" and verification and verification.get("claimed_name"):
        name = verification["claimed_name"]
        amt = verification.get("amount") or "urgent funds"
        ask = verification.get("ask") or "an emergency"
        return {
            "claim": f"The caller claimed to be {name} and urgently requested {amt} for {ask} while asking for secrecy.",
            "pattern": "Grandparent / family-emergency impersonation scam using urgency and secrecy pressure.",
            "action_taken": f"Vouch held the caller, verified out-of-band with {name} ('Not me'), announced the denial, and disconnected before Ruth's phone rang.",
            "next_step": f"Let {name} and the family know a scammer targeted Ruth's number today; no money or personal info was shared.",
        }
    if outcome == "blocked":
        return {
            "claim": verdict or "The caller claimed institutional authority and pushed for immediate financial action.",
            "pattern": "Bank / institution impersonation scam ('safe account' or urgent fraud-department pretext).",
            "action_taken": "Vouch refused the request and ended the call without ringing Ruth's phone.",
            "next_step": "If Ruth wants peace of mind, call the official number printed on the back of her bank card directly.",
        }
    if outcome == "passed":
        return {
            "claim": verdict or "Routine business call with no identity deception or financial request.",
            "pattern": "Legitimate routine call — no scam indicators detected.",
            "action_taken": "Vouch screened the caller and connected the call to Ruth with a one-line summary.",
            "next_step": "No security follow-up needed.",
        }
    return {
        "claim": verdict or "Caller could not be verified during screening.",
        "pattern": "Unverified caller held by Vouch.",
        "action_taken": "Vouch took a brief note instead of ringing Ruth's phone directly.",
        "next_step": "Check with family directly before returning any unfamiliar call.",
    }


def _format_text(s: dict[str, str]) -> str:
    return (
        f"Claim: {s['claim']}\n"
        f"Pattern: {s['pattern']}\n"
        f"What Vouch did: {s['action_taken']}\n"
        f"Next step: {s['next_step']}"
    )
