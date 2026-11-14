from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
import wave
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import WebSocket

from server.config import ARTIFACTS_DIR, is_mock_mode, is_test_mode
from server.mock_session import MockScreenerSession
from server.models import (
    CallHistoryItem,
    CallState,
    Room,
    SlidingRateLimiter,
    VerificationRequest,
    format_blocked_headline,
    generate_room_code,
)
from server.report import generate_family_report

logger = logging.getLogger("vouch.hub")


class ScreenerSession(Protocol):
    async def start(self) -> None: ...
    async def send_audio(self, pcm16k: bytes) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def close(self) -> None: ...


@dataclass
class ConnectedClient:
    ws: WebSocket
    role: str  # "caller" | "senior" | "family" | "demo"
    client_ip: str = "127.0.0.1"


class RoomSessionController:
    """Bridges a single Room's active call with either MockScreenerSession or GeminiLiveScreenerSession."""

    def __init__(
        self,
        hub: RoomHub,
        room: Room,
        call_id: str,
        verification_timeout_s: float = 25.0,
        max_call_seconds: float = 180.0,
    ) -> None:
        self.hub = hub
        self.room = room
        self.call_id = call_id
        self.verification_timeout_s = verification_timeout_s
        self.max_call_seconds = max_call_seconds
        self.session: ScreenerSession | None = None
        self._closed = False
        self._watchdog_task: asyncio.Task | None = None
        self._terminal_outcome: str | None = None
        self._terminal_verdict_text: str = ""
        self._terminal_scam_type: str = ""
        self._awaiting_post_tap_audio = False
        self._test_audio_chunks: list[bytes] = []
        self._assistant_audio_bytes_post_tap: int = 0
        self._caller_speaking: bool = False
        self._last_caller_voice_ts: float = 0.0
        self._report_started: bool = False

    async def start(self) -> None:
        if is_mock_mode():
            self.session = MockScreenerSession(self)
        else:
            from server.live_session import GeminiLiveScreenerSession

            self.session = GeminiLiveScreenerSession(self)

        self._watchdog_task = asyncio.create_task(self._call_duration_watchdog())
        await self.session.start()

    async def _call_duration_watchdog(self) -> None:
        try:
            await asyncio.sleep(self.max_call_seconds)
            if not self._closed and self.room.active_call_id == self.call_id:
                logger.info("Call %s in room %s hit %ss limit; ending.", self.call_id, self.room.code, self.max_call_seconds)
                await self.end_call(reason="Call time limit (3m) reached")
        except asyncio.CancelledError:
            pass

    def mark_caller_speech_end(self) -> None:
        if self.room.metrics.first_assistant_audio_at is not None:
            return
        now = time.time()
        if self.room.metrics.caller_speech_ended_at is None:
            self.room.metrics.caller_speech_ended_at = (
                self._last_caller_voice_ts if self._last_caller_voice_ts > 0 else now
            )

    async def handle_caller_audio(self, pcm16k: bytes) -> None:
        if self._closed or not self.session:
            return
        self.room.touch()
        if (
            len(pcm16k) >= 4
            and self.room.state == CallState.SCREENING
            and self.room.metrics.first_assistant_audio_at is None
        ):
            samples = memoryview(pcm16k[: len(pcm16k) & ~1]).cast("h")
            # Fast subsampled mean absolute amplitude
            step = max(1, len(samples) // 64)
            mean_abs = sum(abs(samples[i]) for i in range(0, len(samples), step)) / (
                max(1, len(range(0, len(samples), step)))
            )
            now = time.time()
            if mean_abs > 380:
                self._caller_speaking = True
                self._last_caller_voice_ts = now
                notify_fn = getattr(self.session, "notify_caller_voice_activity", None)
                if callable(notify_fn):
                    notify_fn()
            elif self._caller_speaking and (now - self._last_caller_voice_ts) >= 0.28:
                self._caller_speaking = False
                self.room.metrics.caller_speech_ended_at = self._last_caller_voice_ts
        await self.session.send_audio(pcm16k)

    async def handle_caller_text(self, text: str) -> None:
        if self._closed or not self.session:
            return
        clean = text.strip()
        if not clean:
            return
        self.room.touch()
        await self.session.send_text(clean)

    async def on_caller_transcript(self, text: str, final: bool = False) -> None:
        if self._closed or self.room.active_call_id != self.call_id:
            return
        entry = self.room.add_or_merge_transcript("caller", text, final=final)
        if entry:
            await self.hub.broadcast_json(
                self.room.code,
                {
                    "type": "transcript",
                    "speaker": "caller",
                    "text": entry.text,
                    "final": entry.final,
                },
            )

    async def on_assistant_transcript(self, text: str, final: bool = False) -> None:
        if self._closed or self.room.active_call_id != self.call_id:
            return
        entry = self.room.add_or_merge_transcript("assistant", text, final=final)
        if entry:
            await self.hub.broadcast_json(
                self.room.code,
                {
                    "type": "transcript",
                    "speaker": "assistant",
                    "text": entry.text,
                    "final": entry.final,
                },
            )

    async def on_turn_complete(self) -> None:
        if self._closed or self.room.active_call_id != self.call_id:
            return
        for spk in ("caller", "assistant"):
            fin = self.room.finalize_speaker_transcript(spk)
            if fin:
                await self.hub.broadcast_json(
                    self.room.code,
                    {
                        "type": "transcript",
                        "speaker": spk,
                        "text": fin.text,
                        "final": True,
                    },
                )

    async def on_assistant_interrupted(self) -> None:
        if self._closed or self.room.active_call_id != self.call_id:
            return
        await self.hub.broadcast_json(
            self.room.code,
            {"type": "assistant_interrupted"},
        )

    async def on_assistant_audio(self, pcm24k: bytes) -> None:
        if self._closed or self.room.active_call_id != self.call_id or not pcm24k:
            return
        now = time.time()
        metrics_updated = False
        if self.room.metrics.first_assistant_audio_at is None:
            if self.room.metrics.caller_speech_ended_at is None and self._last_caller_voice_ts > 0:
                self.room.metrics.caller_speech_ended_at = self._last_caller_voice_ts
                self._caller_speaking = False
            if self.room.metrics.caller_speech_ended_at is not None:
                self.room.metrics.first_assistant_audio_at = now
                metrics_updated = True
        if self._awaiting_post_tap_audio and self.room.metrics.post_tap_first_audio_at is None:
            self.room.metrics.post_tap_first_audio_at = now
            metrics_updated = True
        if self._awaiting_post_tap_audio:
            self._assistant_audio_bytes_post_tap += len(pcm24k)

        if is_test_mode():
            self._test_audio_chunks.append(pcm24k)

        await self.hub.broadcast_audio(self.room.code, pcm24k)
        if metrics_updated:
            await self.hub.broadcast_json(
                self.room.code,
                {"type": "metrics", "metrics": self.room.metrics.to_dict()},
            )

    # --- Tool Handlers ---

    async def tool_request_family_verification(
        self,
        claimed_name: str,
        relationship: str = "family member",
        ask: str = "urgent request",
        amount: str = "",
    ) -> str:
        if self._closed or self.room.active_call_id != self.call_id:
            return "timeout"

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        ver_id = uuid.uuid4().hex[:8]
        ver = VerificationRequest(
            id=ver_id,
            claimed_name=(claimed_name or "Unknown").strip(),
            relationship=(relationship or "family member").strip(),
            ask=(ask or "urgent request").strip(),
            amount=(amount or "").strip(),
            future=fut,
        )
        self.room.verification = ver
        if self.room.state == CallState.SCREENING:
            self.room.transition(CallState.VERIFYING)
            await self.hub.broadcast_json(
                self.room.code, {"type": "status", "state": CallState.VERIFYING.value}
            )

        await self.hub.broadcast_json(
            self.room.code,
            {
                "type": "verification_requested",
                "id": ver.id,
                "claimed_name": ver.claimed_name,
                "relationship": ver.relationship,
                "ask": ver.ask,
                "amount": ver.amount,
            },
        )

        try:
            answer = await asyncio.wait_for(fut, timeout=self.verification_timeout_s)
        except asyncio.TimeoutError:
            answer = "timeout"
            ver.answer = "timeout"
            ver.answered_at = time.time()
            await self.hub.broadcast_json(
                self.room.code,
                {"type": "verification_answered", "id": ver.id, "answer": "timeout"},
            )

        return answer

    async def submit_verification_answer(self, ver_id: str | None, answer: str) -> bool:
        ver = self.room.verification
        if not ver or ver.answer is not None:
            return False
        if ver_id and ver.id != ver_id:
            return False
        if answer not in ("confirmed", "denied"):
            return False

        now = time.time()
        ver.answer = answer
        ver.answered_at = now
        self.room.metrics.verification_tapped_at = now
        if is_mock_mode():
            self._awaiting_post_tap_audio = True

        await self.hub.broadcast_json(
            self.room.code,
            {"type": "verification_answered", "id": ver.id, "answer": answer},
        )
        if ver.future and not ver.future.done():
            ver.future.set_result(answer)
        return True

    async def tool_block_call(self, reason: str, scam_type: str = "impersonation") -> str:
        if self._closed or self.room.active_call_id != self.call_id:
            return "ok"
        headline = format_blocked_headline(reason, scam_type, self.room.verification)
        if self.room.state in (CallState.SCREENING, CallState.VERIFYING):
            self.room.transition(CallState.BLOCKED)
        self._terminal_outcome = "blocked"
        self._terminal_verdict_text = headline
        self._terminal_scam_type = scam_type
        self.room.last_verdict = {
            "outcome": "blocked",
            "headline": headline,
            "reason": reason,
            "scam_type": scam_type,
        }
        await self.hub.broadcast_json(
            self.room.code, {"type": "status", "state": CallState.BLOCKED.value}
        )
        await self.hub.broadcast_json(
            self.room.code,
            {
                "type": "call_blocked",
                "reason": reason,
                "scam_type": scam_type,
                "headline": headline,
            },
        )
        self._maybe_start_background_report(delay_s=0.45)
        return "call_marked_blocked"

    async def tool_pass_through(self, summary: str) -> str:
        if self._closed or self.room.active_call_id != self.call_id:
            return "ok"
        clean_summary = summary.strip() or "Verified caller connected to Ruth."
        if self.room.state in (CallState.SCREENING, CallState.VERIFYING):
            self.room.transition(CallState.PASSED)
        self._terminal_outcome = "passed"
        self._terminal_verdict_text = f"Passed through: {clean_summary}"
        self.room.last_verdict = {
            "outcome": "passed",
            "headline": f"Ringing Ruth: {clean_summary}",
            "summary": clean_summary,
        }
        await self.hub.broadcast_json(
            self.room.code, {"type": "status", "state": CallState.PASSED.value}
        )
        await self.hub.broadcast_json(
            self.room.code,
            {"type": "call_passed_through", "summary": clean_summary},
        )
        self._maybe_start_background_report(delay_s=0.45)
        return "call_passed_through"

    async def tool_take_message(self, summary: str) -> str:
        if self._closed or self.room.active_call_id != self.call_id:
            return "ok"
        clean_summary = summary.strip() or "Caller left a message for Ruth."
        if self.room.state in (CallState.SCREENING, CallState.VERIFYING):
            self.room.transition(CallState.MESSAGE_TAKEN)
        self._terminal_outcome = "message_taken"
        self._terminal_verdict_text = f"Message taken: {clean_summary}"
        self.room.last_verdict = {
            "outcome": "message_taken",
            "headline": f"Message taken: {clean_summary}",
            "summary": clean_summary,
        }
        await self.hub.broadcast_json(
            self.room.code, {"type": "status", "state": CallState.MESSAGE_TAKEN.value}
        )
        await self.hub.broadcast_json(
            self.room.code,
            {"type": "call_message_taken", "summary": clean_summary},
        )
        self._maybe_start_background_report(delay_s=0.45)
        return "message_recorded"

    async def finish_call_after_speech(self, delay_s: float = 0.25) -> None:
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        await self.end_call()

    def _write_test_artifacts(self) -> None:
        if not is_test_mode():
            return
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        pcm_bytes = b"".join(self._test_audio_chunks)
        for prefix in (f"call_{self.call_id}", "latest"):
            wav_path = ARTIFACTS_DIR / f"{prefix}_assistant.wav"
            txt_path = ARTIFACTS_DIR / f"{prefix}_transcript.txt"
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm_bytes)
            lines = [
                f"[{t.speaker}] {t.text}"
                for t in self.room.transcripts
            ]
            txt_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    async def end_call(self, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True

        if self._watchdog_task:
            self._watchdog_task.cancel()

        if self.session:
            try:
                await self.session.close()
            except Exception as exc:
                logger.debug("Error closing session: %s", exc)

        # Finalize any streaming transcripts
        for spk in ("caller", "assistant"):
            fin = self.room.finalize_speaker_transcript(spk)
            if fin:
                await self.hub.broadcast_json(
                    self.room.code,
                    {
                        "type": "transcript",
                        "speaker": spk,
                        "text": fin.text,
                        "final": True,
                    },
                )

        # Cancel any pending verification future cleanly
        if self.room.verification and self.room.verification.future and not self.room.verification.future.done():
            self.room.verification.future.cancel()

        self._write_test_artifacts()

        outcome = self._terminal_outcome or (
            self.room.state.value
            if self.room.state in (CallState.BLOCKED, CallState.PASSED, CallState.MESSAGE_TAKEN)
            else "ended"
        )
        verdict_text = self._terminal_verdict_text or reason or "Call ended."

        history_item: CallHistoryItem | None = None
        if outcome in ("blocked", "passed", "message_taken") or self.room.transcripts:
            history_item = CallHistoryItem(
                call_id=self.call_id,
                timestamp=time.time(),
                outcome=outcome,
                headline=verdict_text,
                detail=reason or verdict_text,
                scam_type=self._terminal_scam_type,
            )
            self.room.history.insert(0, history_item)
            self.room.history = self.room.history[:20]

        report_input = {
            "call_id": self.call_id,
            "outcome": outcome,
            "verdict_text": verdict_text,
            "verification": self.room.verification.to_dict() if self.room.verification else None,
            "transcripts": [t.to_dict() for t in self.room.transcripts],
        }

        self.room.active_call_id = None
        metrics_dict = self.room.metrics.to_dict()
        post_tap_audio_s = round(self._assistant_audio_bytes_post_tap / (24000 * 2), 3)
        metrics_dict["post_tap_audio_duration_s"] = post_tap_audio_s

        await self.hub.broadcast_json(
            self.room.code,
            {
                "type": "call_ended",
                "call_id": self.call_id,
                "final_state": outcome,
                "verdict_text": verdict_text,
                "history_item": history_item.to_dict() if history_item else None,
                "metrics": metrics_dict,
            },
        )

        # Transition back to idle after terminal state per SPEC (`passed | blocked | message_taken -> idle`)
        self.room.transition(CallState.IDLE)
        await self.hub.broadcast_json(
            self.room.code, {"type": "status", "state": CallState.IDLE.value}
        )

        # Kick off Gemini 4 Carbon post-call report in background without blocking call flow
        if outcome in ("blocked", "passed", "message_taken") and not self._report_started:
            self._report_started = True
            asyncio.create_task(self._emit_background_report(report_input))

    def _maybe_start_background_report(self, delay_s: float = 0.45) -> None:
        if self._report_started or not self._terminal_outcome:
            return
        self._report_started = True
        asyncio.create_task(self._delayed_background_report(delay_s))

    async def _delayed_background_report(self, delay_s: float) -> None:
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        report_input = {
            "call_id": self.call_id,
            "outcome": self._terminal_outcome or "ended",
            "verdict_text": self._terminal_verdict_text,
            "verification": self.room.verification.to_dict() if self.room.verification else None,
            "transcripts": [t.to_dict() for t in self.room.transcripts],
        }
        await self._emit_background_report(report_input)

    async def _emit_background_report(self, report_input: dict[str, Any]) -> None:
        try:
            report_event = await generate_family_report(report_input)
            self.room.last_report = report_event
            await self.hub.broadcast_json(self.room.code, report_event)
        except Exception as exc:
            logger.warning("Background report task failed: %s", exc)


class CapacityError(Exception):
    pass


class RateLimitError(Exception):
    pass


class RoomHub:
    """In-memory room manager & WebSocket broadcast hub."""

    def __init__(
        self,
        max_rooms: int | None = None,
        max_call_seconds: float | None = None,
        verification_timeout_s: float | None = None,
        rate_limit_per_min: int | None = None,
    ) -> None:
        self.max_rooms = max_rooms or int(os.getenv("VOUCH_MAX_ROOMS", "5"))
        self.max_call_seconds = max_call_seconds or float(
            os.getenv("VOUCH_MAX_CALL_SECONDS", "180")
        )
        self.verification_timeout_s = verification_timeout_s or float(
            os.getenv("VOUCH_VERIFICATION_TIMEOUT", "25")
        )
        rl_max = rate_limit_per_min or int(os.getenv("VOUCH_RATE_LIMIT_PER_MIN", "25"))
        self.rate_limiter = SlidingRateLimiter(max_calls=rl_max, window_seconds=60.0)

        self.rooms: dict[str, Room] = {}
        self.clients: dict[str, list[ConnectedClient]] = {}
        self.controllers: dict[str, RoomSessionController] = {}

    def create_or_get_room(self, code: str | None = None) -> Room:
        if code:
            norm = code.strip().upper()
            if norm in self.rooms:
                self.rooms[norm].touch()
                return self.rooms[norm]
            self._ensure_room_capacity()
            room = Room(code=norm)
            self.rooms[norm] = room
            self.clients.setdefault(norm, [])
            return room

        self._ensure_room_capacity()
        for _ in range(20):
            cand = generate_room_code()
            if cand not in self.rooms:
                room = Room(code=cand)
                self.rooms[cand] = room
                self.clients.setdefault(cand, [])
                return room
        raise CapacityError("Could not allocate unique room code")

    def latest_or_create_room(self) -> Room:
        if self.rooms:
            latest = max(self.rooms.values(), key=lambda r: r.last_active_at)
            return latest
        return self.create_or_get_room()

    def _ensure_room_capacity(self) -> None:
        if len(self.rooms) < self.max_rooms:
            return
        # Evict oldest room that does NOT have an active call
        idle_rooms = [
            r for r in self.rooms.values() if not r.is_call_active()
        ]
        if idle_rooms:
            oldest = min(idle_rooms, key=lambda r: r.last_active_at)
            self.rooms.pop(oldest.code, None)
            self.clients.pop(oldest.code, None)
            self.controllers.pop(oldest.code, None)
            return
        raise CapacityError(
            f"Maximum concurrent active rooms ({self.max_rooms}) reached. Please try again in a minute."
        )

    def register_client(self, room_code: str, ws: WebSocket, role: str, client_ip: str) -> Room:
        room = self.create_or_get_room(room_code)
        self.clients.setdefault(room.code, []).append(
            ConnectedClient(ws=ws, role=role, client_ip=client_ip)
        )
        return room

    def unregister_client(self, room_code: str, ws: WebSocket) -> None:
        code = room_code.upper()
        conns = self.clients.get(code, [])
        self.clients[code] = [c for c in conns if c.ws is not ws]

    async def start_call(self, room_code: str, client_ip: str = "127.0.0.1") -> RoomSessionController:
        if not self.rate_limiter.allow(client_ip):
            raise RateLimitError("Too many calls started from this IP. Please wait a moment.")

        room = self.create_or_get_room(room_code)
        prev = self.controllers.get(room.code)
        if prev and not prev._closed:
            await prev.end_call(reason="New call started")

        call_id = room.start_new_call()
        ctrl = RoomSessionController(
            hub=self,
            room=room,
            call_id=call_id,
            verification_timeout_s=self.verification_timeout_s,
            max_call_seconds=self.max_call_seconds,
        )
        self.controllers[room.code] = ctrl

        await self.broadcast_json(
            room.code,
            {"type": "call_started", "call_id": call_id, "started_at": room.call_started_at},
        )
        await self.broadcast_json(
            room.code,
            {"type": "status", "state": CallState.SCREENING.value},
        )
        await ctrl.start()
        return ctrl

    async def end_call(self, room_code: str, reason: str = "Caller hung up") -> None:
        code = room_code.upper()
        ctrl = self.controllers.get(code)
        if ctrl and not ctrl._closed:
            await ctrl.end_call(reason=reason)

    async def broadcast_json(self, room_code: str, payload: dict[str, Any]) -> None:
        code = room_code.upper()
        conns = list(self.clients.get(code, []))
        stale: list[WebSocket] = []
        for c in conns:
            try:
                await c.ws.send_json(payload)
            except Exception:
                stale.append(c.ws)
        for ws in stale:
            self.unregister_client(code, ws)

    async def broadcast_audio(self, room_code: str, pcm24k: bytes) -> None:
        """Send 24kHz PCM assistant audio to caller (and standalone demo if subscribed)."""
        code = room_code.upper()
        conns = list(self.clients.get(code, []))
        stale: list[WebSocket] = []
        for c in conns:
            if c.role != "caller":
                continue
            try:
                await c.ws.send_bytes(pcm24k)
            except Exception:
                stale.append(c.ws)
        for ws in stale:
            self.unregister_client(code, ws)
