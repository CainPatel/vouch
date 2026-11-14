from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from google import genai
from google.genai import types

from server.config import discover_models, load_screener_prompt

if TYPE_CHECKING:
    from server.hub import RoomSessionController

logger = logging.getLogger("vouch.live")


def build_screener_tools() -> list[types.Tool]:
    req_verify = types.FunctionDeclaration(
        name="request_family_verification",
        description=(
            "Start an out-of-band verification alert on the real family member's phone whenever an unknown caller "
            "claims to be a family member (e.g., Jake, Maya) or claims to call on a family member's behalf. "
            "Returns immediately while the family member responds on their phone."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "claimed_name": types.Schema(
                    type=types.Type.STRING,
                    description="Name of the family member the caller claims to be (e.g., 'Jake').",
                ),
                "relationship": types.Schema(
                    type=types.Type.STRING,
                    description="Claimed relationship to Ruth (e.g., 'grandson', 'daughter').",
                ),
                "ask": types.Schema(
                    type=types.Type.STRING,
                    description="What the caller is asking for or claiming happened (e.g., 'bail money', 'urgent help').",
                ),
                "amount": types.Schema(
                    type=types.Type.STRING,
                    description="Dollar amount requested if mentioned (e.g., '$4,000'), else empty string.",
                ),
            },
            required=["claimed_name", "ask"],
        ),
    )

    block_fn = types.FunctionDeclaration(
        name="block_call",
        description=(
            "Record that this call is blocked (after family verification is denied, or immediately when a caller "
            "claims to be a bank, fraud department, government agency, or tech support)."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "reason": types.Schema(
                    type=types.Type.STRING,
                    description="Short plain-English reason the call was blocked.",
                ),
                "scam_type": types.Schema(
                    type=types.Type.STRING,
                    description="Category such as 'family_impersonation' or 'institution_impersonation'.",
                ),
            },
            required=["reason", "scam_type"],
        ),
    )

    pass_fn = types.FunctionDeclaration(
        name="pass_through",
        description=(
            "Connect a legitimate ordinary business caller (such as a pharmacy or doctor's office with no money/account ask) "
            "or a confirmed family member through to Ruth."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "summary": types.Schema(
                    type=types.Type.STRING,
                    description="One-line summary shown to Ruth when her phone rings.",
                ),
            },
            required=["summary"],
        ),
    )

    msg_fn = types.FunctionDeclaration(
        name="take_message",
        description="Record a message without ringing Ruth when family verification times out.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "summary": types.Schema(
                    type=types.Type.STRING,
                    description="One-line summary of the caller's message.",
                ),
            },
            required=["summary"],
        ),
    )

    return [types.Tool(function_declarations=[req_verify, block_fn, pass_fn, msg_fn])]


class GeminiLiveScreenerSession:
    """Manages a bidirectional Gemini Live API audio + tool session for one call."""

    def __init__(self, controller: RoomSessionController) -> None:
        self.controller = controller
        self._closed = False
        self._ready = asyncio.Event()
        self._session: Any = None
        self._runner_task: asyncio.Task | None = None
        self._greeting_task: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()
        self._caller_spoke = False
        self._on_hold = False
        self._pending_hangup = False
        self._verification_outcome: str | None = None
        self._verified_name: str = ""
        self._verified_amount: str = ""
        self._turn_audio_bytes: int = 0
        self._total_audio_bytes: int = 0
        self._post_tap_audio_bytes: int = 0
        self._in_model_turn: bool = False
        self._arm_post_tap_on_turn_break: bool = False
        self._active_model: str = ""

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def start(self) -> None:
        self._runner_task = asyncio.create_task(self._session_lifecycle())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("Timed out waiting for Gemini Live session to open")
            raise

    def _build_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=load_screener_prompt(),
            tools=build_screener_tools(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    silence_duration_ms=450,
                    prefix_padding_ms=150,
                )
            ),
        )

    async def _session_lifecycle(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            logger.error("GEMINI_API_KEY not set!")
            self._ready.set()
            return

        models = discover_models()
        candidates = [models.live_model] + models.live_fallbacks
        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

        last_err: Exception | None = None
        for model_id in candidates:
            if self._closed:
                return
            try:
                config = self._build_config()
                logger.info("Connecting Gemini Live session with model=%s", model_id)
                async with client.aio.live.connect(model=model_id, config=config) as session:
                    self._session = session
                    self._active_model = model_id
                    self._ready.set()
                    self._greeting_task = asyncio.create_task(self._maybe_send_opening_greeting())
                    await self._receive_loop(session)
                    return
            except asyncio.CancelledError:
                return
            except Exception as exc:
                last_err = exc
                logger.warning("Live model %s failed (%s); trying next fallback if available", model_id, exc)
                if self._ready.is_set():
                    break

        if not self._ready.is_set():
            logger.error("All Live models failed; last error: %s", last_err)
            self._ready.set()

    async def _maybe_send_opening_greeting(self) -> None:
        try:
            await asyncio.sleep(2.2)
            if not self._closed and not self._caller_spoke and self._session:
                await self._session.send_client_content(
                    turns=[
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": "[System: Call connected and caller is waiting silently. Greet them with: 'Hello, this is Ruth's assistant. Who's calling, and what is it about?']"
                                }
                            ],
                        }
                    ],
                    turn_complete=True,
                )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Opening greeting skipped: %s", exc)

    def notify_caller_voice_activity(self) -> None:
        if not self._caller_spoke:
            self._caller_spoke = True
            if self._greeting_task and not self._greeting_task.done():
                self._greeting_task.cancel()

    async def send_audio(self, pcm16k: bytes) -> None:
        if self._closed or not self._session or not pcm16k:
            return
        # Hold caller line once verification is active or call is ending so hold/closing speech isn't interrupted
        if self._on_hold or self._verification_outcome is not None or self._pending_hangup:
            return
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm16k, mime_type="audio/pcm;rate=16000")
            )
        except Exception as exc:
            if not self._closed:
                logger.debug("send_audio error: %s", exc)

    async def send_text(self, text: str) -> None:
        if self._closed or not self._session or not text:
            return
        self.notify_caller_voice_activity()
        self.controller.mark_caller_speech_end()
        await self.controller.on_caller_transcript(text, final=True)
        try:
            await self._session.send_client_content(
                turns=[{"role": "user", "parts": [{"text": text}]}],
                turn_complete=True,
            )
        except Exception as exc:
            if not self._closed:
                logger.warning("send_text error: %s", exc)

    async def _receive_loop(self, session: Any) -> None:
        while not self._closed:
            try:
                async for response in session.receive():
                    if self._closed:
                        break
                    await self._process_server_message(session, response)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._closed:
                    logger.warning("Live session receive loop ended: %s", exc)
                break

    async def _process_server_message(self, session: Any, response: Any) -> None:
        sc = getattr(response, "server_content", None)
        if sc is not None:
            if getattr(sc, "interrupted", False):
                self._in_model_turn = False
                if self._arm_post_tap_on_turn_break:
                    self._arm_post_tap_on_turn_break = False
                    self.controller._awaiting_post_tap_audio = True
                await self.controller.on_assistant_interrupted()

            in_tr = getattr(sc, "input_transcription", None)
            if in_tr and getattr(in_tr, "text", None):
                self.notify_caller_voice_activity()
                await self.controller.on_caller_transcript(in_tr.text, final=False)

            model_turn = getattr(sc, "model_turn", None)
            if model_turn and getattr(model_turn, "parts", None):
                for part in model_turn.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        self._in_model_turn = True
                        chunk = inline.data
                        self._turn_audio_bytes += len(chunk)
                        self._total_audio_bytes += len(chunk)
                        if self.controller._awaiting_post_tap_audio:
                            self._post_tap_audio_bytes += len(chunk)
                        await self.controller.on_assistant_audio(chunk)

            out_tr = getattr(sc, "output_transcription", None)
            if out_tr and getattr(out_tr, "text", None):
                await self.controller.on_assistant_transcript(out_tr.text, final=False)

            if getattr(sc, "turn_complete", False):
                self._in_model_turn = False
                if self._arm_post_tap_on_turn_break:
                    self._arm_post_tap_on_turn_break = False
                    self.controller._awaiting_post_tap_audio = True
                await self.controller.on_turn_complete()
                await self._on_model_turn_complete()
                self._turn_audio_bytes = 0

        tc = getattr(response, "tool_call", None)
        if tc and getattr(tc, "function_calls", None):
            self._spawn(self._handle_function_calls(session, list(tc.function_calls)))

    async def _on_model_turn_complete(self) -> None:
        # Once verification has resolved AND the assistant has spoken the final reply (>0.5s audio),
        # ensure verdict is recorded and end the call cleanly after playback buffer drains.
        if self._verification_outcome is not None and self._post_tap_audio_bytes >= 12000:
            if self.controller._terminal_outcome is None:
                if self._verification_outcome == "denied":
                    await self.controller.tool_block_call(
                        reason=f"Someone impersonating {self._verified_name or 'family'} asked for {self._verified_amount or 'money'}",
                        scam_type="family_impersonation",
                    )
                elif self._verification_outcome == "confirmed":
                    await self.controller.tool_pass_through(
                        summary=f"Verified call from {self._verified_name or 'family member'}"
                    )
                elif self._verification_outcome == "timeout":
                    await self.controller.tool_take_message(
                        summary=f"Unverified call claiming to be {self._verified_name or 'family member'}"
                    )
            self._pending_hangup = True

        if self._pending_hangup and not self._closed:
            # Wait until spoken closing sentence has actually been generated before hanging up
            if self._verification_outcome is not None and self._post_tap_audio_bytes < 12000:
                return
            if self._verification_outcome is None and self._total_audio_bytes < 12000:
                return
            closing_bytes = self._post_tap_audio_bytes if self._verification_outcome is not None else max(self._turn_audio_bytes, self._total_audio_bytes)
            closing_audio_s = closing_bytes / 48000.0
            drain_s = min(4.5, max(1.5, closing_audio_s * 0.75))
            self._spawn(self.controller.finish_call_after_speech(delay_s=drain_s))

    async def _wait_and_inject_verification_result(
        self,
        session: Any,
        claimed_name: str,
        relationship: str,
        ask: str,
        amount: str,
    ) -> None:
        answer = await self.controller.tool_request_family_verification(
            claimed_name=claimed_name,
            relationship=relationship,
            ask=ask,
            amount=amount,
        )
        if self._closed:
            return

        self._verification_outcome = answer
        if answer == "denied":
            await self.controller.tool_block_call(
                reason=f"Someone impersonating {claimed_name} asked for {amount or ask}",
                scam_type="family_impersonation",
            )
            prompt = (
                f"[System update: {claimed_name} tapped Not me on their phone and the call is now marked blocked. "
                f"Do not call any tools. Reply to the caller out loud right now with only these exact words: "
                f"{claimed_name} says he isn't calling. Goodbye.]"
            )
        elif answer == "confirmed":
            await self.controller.tool_pass_through(
                summary=f"Verified call from {claimed_name} ({relationship})"
            )
            prompt = (
                f"[System update: {claimed_name} tapped Yes on their phone and the call is connecting. "
                f"Do not call any tools. Reply to the caller out loud right now with only these words: "
                f"Confirmed — connecting you with Ruth right now.]"
            )
        else:
            await self.controller.tool_take_message(
                summary=f"Unverified caller claiming to be {claimed_name}"
            )
            prompt = (
                f"[System update: Verification timed out with no answer from {claimed_name} and a message was logged. "
                f"Do not call any tools. Reply to the caller out loud right now with only these words: "
                f"I couldn't confirm that right now. I'll let Ruth know you called.]"
            )

        try:
            if self._in_model_turn:
                self._arm_post_tap_on_turn_break = True
            else:
                self.controller._awaiting_post_tap_audio = True
            await session.send_client_content(
                turns=[{"role": "user", "parts": [{"text": prompt}]}],
                turn_complete=True,
            )
            if self._arm_post_tap_on_turn_break:
                await asyncio.sleep(0.22)
                if self._arm_post_tap_on_turn_break:
                    self._arm_post_tap_on_turn_break = False
                    self.controller._awaiting_post_tap_audio = True
        except Exception as exc:
            logger.warning("Failed to inject verification result turn: %s", exc)

    async def _handle_function_calls(self, session: Any, fcs: list[Any]) -> None:
        responses: list[types.FunctionResponse] = []
        for fc in fcs:
            if self._closed:
                return
            name = fc.name
            args = dict(fc.args or {})
            logger.info("Live tool call: %s(%s)", name, args)

            if name == "request_family_verification":
                self._on_hold = True
                claimed_name = str(args.get("claimed_name") or "Jake")
                relationship = str(args.get("relationship") or "family member")
                ask = str(args.get("ask") or "urgent help")
                amount = str(args.get("amount") or "")
                self._verified_name = claimed_name
                self._verified_amount = amount

                # Spawn background wait for /family tap so we return pending immediately -> model speaks hold line NOW!
                self._spawn(
                    self._wait_and_inject_verification_result(
                        session=session,
                        claimed_name=claimed_name,
                        relationship=relationship,
                        ask=ask,
                        amount=amount,
                    )
                )
                responses.append(
                    types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={
                            "status": "verification_ping_sent",
                            "instruction": (
                                f"Verification card is now active on {claimed_name}'s phone. "
                                f"Speak out loud right now: 'This is Ruth's assistant. One moment while I confirm with {claimed_name}.' "
                                f"Then wait silently until the verification result arrives."
                            ),
                        },
                    )
                )

            elif name == "block_call":
                reason = str(args.get("reason") or "Suspicious call blocked")
                scam_type = str(args.get("scam_type") or "impersonation")
                if self.controller._terminal_outcome is None:
                    await self.controller.tool_block_call(reason=reason, scam_type=scam_type)
                self._pending_hangup = True
                if self._verification_outcome is not None:
                    instr = "Already recorded. Do not repeat anything you already said."
                elif self._turn_audio_bytes >= 12000:
                    instr = "Call marked blocked. Do not add anything further."
                    self._spawn(self.controller.finish_call_after_speech(delay_s=2.4))
                else:
                    instr = (
                        "Call marked blocked. Now tell the caller calmly in one sentence: "
                        "'This is Ruth's assistant. Ruth does not handle financial or security requests on incoming calls and will call the official number directly. Goodbye.'"
                    )
                responses.append(
                    types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"status": "blocked", "instruction": instr},
                    )
                )

            elif name == "pass_through":
                summary = str(args.get("summary") or "Routine call for Ruth")
                await self.controller.tool_pass_through(summary=summary)
                self._pending_hangup = True
                already_spoke = self._turn_audio_bytes >= 12000
                if already_spoke:
                    self._spawn(self.controller.finish_call_after_speech(delay_s=2.4))
                instr = (
                    "Call connected."
                    if already_spoke
                    else "Call marked passed through. Tell the caller politely in one sentence: 'This is Ruth's assistant. Thank you — connecting you with Ruth right now.'"
                )
                responses.append(
                    types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"status": "passed_through", "instruction": instr},
                    )
                )

            elif name == "take_message":
                summary = str(args.get("summary") or "Caller left a message")
                await self.controller.tool_take_message(summary=summary)
                self._pending_hangup = True
                already_spoke = self._post_tap_audio_bytes >= 12000 or self._turn_audio_bytes >= 12000
                instr = (
                    "Message saved."
                    if already_spoke
                    else "Message recorded. Tell the caller: 'I couldn't confirm that right now. I'll let Ruth know you called.'"
                )
                responses.append(
                    types.FunctionResponse(
                        id=fc.id,
                        name=name,
                        response={"status": "message_taken", "instruction": instr},
                    )
                )

        if responses and not self._closed:
            try:
                await session.send_tool_response(function_responses=responses)
            except Exception as exc:
                logger.warning("send_tool_response failed: %s", exc)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._greeting_task:
            self._greeting_task.cancel()
        for t in list(self._bg_tasks):
            t.cancel()
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except (asyncio.CancelledError, Exception):
                pass
