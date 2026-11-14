from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CallState(str, Enum):
    IDLE = "idle"
    SCREENING = "screening"
    VERIFYING = "verifying"
    PASSED = "passed"
    BLOCKED = "blocked"
    MESSAGE_TAKEN = "message_taken"


VALID_TRANSITIONS: dict[CallState, set[CallState]] = {
    CallState.IDLE: {CallState.SCREENING},
    CallState.SCREENING: {
        CallState.VERIFYING,
        CallState.PASSED,
        CallState.BLOCKED,
        CallState.MESSAGE_TAKEN,
        CallState.IDLE,
    },
    CallState.VERIFYING: {
        CallState.PASSED,
        CallState.BLOCKED,
        CallState.MESSAGE_TAKEN,
        CallState.IDLE,
    },
    CallState.PASSED: {CallState.IDLE, CallState.SCREENING},
    CallState.BLOCKED: {CallState.IDLE, CallState.SCREENING},
    CallState.MESSAGE_TAKEN: {CallState.IDLE, CallState.SCREENING},
}

ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_room_code(length: int = 6) -> str:
    return "".join(secrets.choice(ROOM_ALPHABET) for _ in range(length))


@dataclass
class VerificationRequest:
    id: str
    claimed_name: str
    relationship: str
    ask: str
    amount: str
    created_at: float = field(default_factory=time.time)
    answer: str | None = None
    answered_at: float | None = None
    future: asyncio.Future[str] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claimed_name": self.claimed_name,
            "relationship": self.relationship,
            "ask": self.ask,
            "amount": self.amount,
            "answer": self.answer,
        }


@dataclass
class TranscriptEntry:
    speaker: str  # "caller" | "assistant"
    text: str
    final: bool = True
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "final": self.final,
            "ts": self.ts,
        }


@dataclass
class CallHistoryItem:
    call_id: str
    timestamp: float
    outcome: str  # "blocked" | "passed" | "message_taken" | "ended"
    headline: str
    detail: str
    scam_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "headline": self.headline,
            "detail": self.detail,
            "scam_type": self.scam_type,
        }


@dataclass
class LatencyMetrics:
    call_started_at: float | None = None
    caller_speech_ended_at: float | None = None
    first_assistant_audio_at: float | None = None
    verification_tapped_at: float | None = None
    post_tap_first_audio_at: float | None = None

    def speech_to_audio_sec(self) -> float | None:
        if self.caller_speech_ended_at and self.first_assistant_audio_at:
            val = self.first_assistant_audio_at - self.caller_speech_ended_at
            if val >= 0:
                return round(val, 3)
        return None

    def tap_to_audio_sec(self) -> float | None:
        if self.verification_tapped_at and self.post_tap_first_audio_at:
            val = self.post_tap_first_audio_at - self.verification_tapped_at
            if val >= 0:
                return round(val, 3)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "speech_to_first_audio_s": self.speech_to_audio_sec(),
            "tap_to_first_audio_s": self.tap_to_audio_sec(),
        }


def format_blocked_headline(
    reason: str,
    scam_type: str,
    verification: VerificationRequest | None,
) -> str:
    """Format Ruth's blocked verdict card cleanly (matching SPEC section 1 step 5)."""
    if verification and verification.claimed_name:
        name = verification.claimed_name.strip()
        amt = (verification.amount or "").strip()
        ask = (verification.ask or "").strip()
        if amt:
            return f"Blocked: someone impersonating {name} asked for {amt}."
        if ask:
            return f"Blocked: someone impersonating {name} asked for {ask}."
        return f"Blocked: someone impersonating {name} tried to reach Ruth."
    clean_reason = reason.strip().rstrip(".")
    if clean_reason.lower().startswith("blocked:"):
        return f"{clean_reason}."
    return f"Blocked: {clean_reason}."


@dataclass
class Room:
    code: str
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    state: CallState = CallState.IDLE
    active_call_id: str | None = None
    call_started_at: float | None = None
    transcripts: list[TranscriptEntry] = field(default_factory=list)
    verification: VerificationRequest | None = None
    last_verdict: dict[str, Any] | None = None
    last_report: dict[str, Any] | None = None
    history: list[CallHistoryItem] = field(default_factory=list)
    metrics: LatencyMetrics = field(default_factory=LatencyMetrics)

    def touch(self) -> None:
        self.last_active_at = time.time()

    def is_call_active(self) -> bool:
        return self.active_call_id is not None and self.state in (
            CallState.SCREENING,
            CallState.VERIFYING,
        )

    def transition(self, target: CallState) -> CallState:
        if target == self.state:
            return self.state
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if target not in allowed:
            raise ValueError(f"Invalid state transition: {self.state} -> {target}")
        self.state = target
        self.touch()
        return self.state

    def start_new_call(self) -> str:
        if self.state != CallState.IDLE:
            self.state = CallState.IDLE
        self.transition(CallState.SCREENING)
        call_id = uuid.uuid4().hex[:10]
        self.active_call_id = call_id
        self.call_started_at = time.time()
        self.transcripts = []
        self.verification = None
        self.last_verdict = None
        self.last_report = None
        self.metrics = LatencyMetrics(call_started_at=self.call_started_at)
        return call_id

    def add_or_merge_transcript(
        self, speaker: str, text: str, final: bool = True
    ) -> TranscriptEntry | None:
        cleaned = text.strip() if final else text
        if not cleaned or not cleaned.strip():
            return None
        self.touch()
        # Live API streams incremental chunks; merge consecutive non-final chunks from same speaker
        if (
            self.transcripts
            and self.transcripts[-1].speaker == speaker
            and not self.transcripts[-1].final
        ):
            prev = self.transcripts[-1]
            # Append with smart spacing for streaming ASR tokens
            if prev.text and not prev.text.endswith(" ") and not text.startswith((" ", ".", ",", "?", "!", "'", "’")):
                prev.text = f"{prev.text} {text.lstrip()}"
            else:
                prev.text = f"{prev.text}{text}"
            prev.final = final
            prev.ts = time.time()
            return prev
        entry = TranscriptEntry(speaker=speaker, text=cleaned.strip(), final=final)
        self.transcripts.append(entry)
        return entry

    def finalize_speaker_transcript(self, speaker: str) -> TranscriptEntry | None:
        if (
            self.transcripts
            and self.transcripts[-1].speaker == speaker
            and not self.transcripts[-1].final
        ):
            self.transcripts[-1].final = True
            return self.transcripts[-1]
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "room_snapshot",
            "room": self.code,
            "state": self.state.value,
            "call_id": self.active_call_id,
            "transcripts": [t.to_dict() for t in self.transcripts],
            "verification": self.verification.to_dict() if self.verification else None,
            "last_verdict": self.last_verdict,
            "last_report": self.last_report,
            "history": [h.to_dict() for h in self.history[:10]],
            "metrics": self.metrics.to_dict(),
        }


class SlidingRateLimiter:
    """Simple in-memory per-IP rate limiter on starting calls."""

    def __init__(self, max_calls: int = 20, window_seconds: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        cutoff = ts - self.window_seconds
        bucket = [t for t in self._hits.get(key, []) if t > cutoff]
        if len(bucket) >= self.max_calls:
            self._hits[key] = bucket
            return False
        bucket.append(ts)
        self._hits[key] = bucket
        return True
