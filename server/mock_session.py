from __future__ import annotations

import asyncio
import math
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.hub import RoomSessionController


def _generate_tone_pcm24k(duration_s: float = 0.25, freq_hz: float = 440.0) -> bytes:
    """Generate short gentle 24kHz 16-bit mono PCM audio for mock-mode testing."""
    sample_rate = 24000
    n_samples = int(sample_rate * duration_s)
    buf = bytearray(n_samples * 2)
    for i in range(n_samples):
        env = min(1.0, i / 400.0, (n_samples - i) / 400.0)
        val = int(3200 * env * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate)))
        struct.pack_into("<h", buf, i * 2, val)
    return bytes(buf)


class MockScreenerSession:
    """Keyword-based stand-in for Gemini (`VOUCH_MOCK=1` only, never shipped)."""

    def __init__(self, controller: RoomSessionController) -> None:
        self.controller = controller
        self._closed = False
        self._tasks: set[asyncio.Task] = set()
        self._audio_bytes_received = 0
        self._triggered_from_audio = False

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def start(self) -> None:
        greeting = "Hello, this is Ruth's assistant. Who's calling, and what is it about?"
        await self.controller.on_assistant_transcript(greeting, final=True)
        await self.controller.on_assistant_audio(_generate_tone_pcm24k(0.2, 420.0))

    async def send_audio(self, pcm16k: bytes) -> None:
        if self._closed:
            return
        self._audio_bytes_received += len(pcm16k)
        # If mock receives >1.5s of raw audio without text, simulate grandson scenario
        if not self._triggered_from_audio and self._audio_bytes_received >= 48000:
            self._triggered_from_audio = True
            await self.send_text(
                "Grandma, it's Jake. I'm in trouble, I need $4,000 for bail. Please don't tell Mom."
            )

    async def send_text(self, text: str) -> None:
        if self._closed:
            return
        self.controller.mark_caller_speech_end()
        await self.controller.on_caller_transcript(text, final=True)
        self._spawn(self._handle_caller_turn(text))

    async def _handle_caller_turn(self, text: str) -> None:
        lower = text.lower()
        if any(k in lower for k in ("jake", "maya", "grandma", "grandson", "bail")):
            claimed_name = "Maya" if "maya" in lower else "Jake"
            rel = "daughter" if claimed_name == "Maya" else "grandson"
            amount = "$4,000" if ("4,000" in lower or "4000" in lower) else "$2,000"
            ask = "bail" if "bail" in lower else "emergency money"

            hold_line = f"This is Ruth's assistant. One moment while I confirm with {claimed_name}."
            await self.controller.on_assistant_audio(_generate_tone_pcm24k(0.3, 440.0))
            await self.controller.on_assistant_transcript(hold_line, final=True)

            result = await self.controller.tool_request_family_verification(
                claimed_name=claimed_name,
                relationship=rel,
                ask=ask,
                amount=amount,
            )
            if self._closed:
                return
            if result == "denied":
                reply = f"{claimed_name} says he isn't calling. Goodbye."
                await self.controller.on_assistant_audio(_generate_tone_pcm24k(1.15, 360.0))
                await self.controller.on_assistant_transcript(reply, final=True)
                await self.controller.tool_block_call(
                    reason=f"Someone impersonating {claimed_name} asked for {amount}",
                    scam_type="family_impersonation",
                )
                await self.controller.finish_call_after_speech()
            elif result == "confirmed":
                reply = "Confirmed — connecting you to Ruth now."
                await self.controller.on_assistant_audio(_generate_tone_pcm24k(0.4, 520.0))
                await self.controller.on_assistant_transcript(reply, final=True)
                await self.controller.tool_pass_through(
                    summary=f"Verified call from {claimed_name} ({rel})"
                )
                await self.controller.finish_call_after_speech()
            else:
                reply = "I couldn't confirm that right now. I'll let Ruth know you called."
                await self.controller.on_assistant_audio(_generate_tone_pcm24k(0.4, 400.0))
                await self.controller.on_assistant_transcript(reply, final=True)
                await self.controller.tool_take_message(
                    summary=f"Unverified caller claiming to be {claimed_name} ({ask})"
                )
                await self.controller.finish_call_after_speech()
            return

        if any(
            k in lower
            for k in ("bank", "fraud", "safe account", "irs", "social security", "tech support", "microsoft")
        ):
            reply = (
                "This is Ruth's assistant. Ruth does not handle bank or account security matters on incoming calls — "
                "she will call the official number on her card directly. Goodbye."
            )
            await self.controller.on_assistant_audio(_generate_tone_pcm24k(0.6, 350.0))
            await self.controller.on_assistant_transcript(reply, final=True)
            await self.controller.tool_block_call(
                reason="Caller claimed to be bank fraud department asking to move funds",
                scam_type="institution_impersonation",
            )
            await self.controller.finish_call_after_speech()
            return

        if any(k in lower for k in ("pharmacy", "prescription", "doctor", "clinic", "elm street")):
            reply = "This is Ruth's assistant. Thank you — I'll connect you with Ruth right now."
            await self.controller.on_assistant_audio(_generate_tone_pcm24k(0.5, 520.0))
            await self.controller.on_assistant_transcript(reply, final=True)
            await self.controller.tool_pass_through(
                summary="Dana from Elm Street Pharmacy — prescription ready for pickup"
            )
            await self.controller.finish_call_after_speech()
            return

        reply = "This is Ruth's assistant. Could you tell me your name and what your call is regarding?"
        await self.controller.on_assistant_audio(_generate_tone_pcm24k(0.3, 440.0))
        await self.controller.on_assistant_transcript(reply, final=True)

    async def close(self) -> None:
        self._closed = True
        for t in list(self._tasks):
            t.cancel()
