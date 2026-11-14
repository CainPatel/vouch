from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ["VOUCH_MOCK"] = "1"

from server.hub import CapacityError, RateLimitError, RoomHub, RoomSessionController
from server.main import app
from server.models import CallState, Room, SlidingRateLimiter, format_blocked_headline


def test_state_machine_transitions():
    room = Room(code="TEST01")
    assert room.state == CallState.IDLE
    with pytest.raises(ValueError):
        room.transition(CallState.BLOCKED)

    room.transition(CallState.SCREENING)
    assert room.state == CallState.SCREENING
    room.transition(CallState.VERIFYING)
    assert room.state == CallState.VERIFYING
    room.transition(CallState.BLOCKED)
    assert room.state == CallState.BLOCKED
    room.transition(CallState.IDLE)
    assert room.state == CallState.IDLE


@pytest.mark.asyncio
async def test_verification_timeout():
    hub = RoomHub(verification_timeout_s=0.08)
    room = hub.create_or_get_room("TMOUT1")
    call_id = room.start_new_call()
    ctrl = RoomSessionController(
        hub=hub, room=room, call_id=call_id, verification_timeout_s=0.08
    )
    ans = await ctrl.tool_request_family_verification(
        claimed_name="Jake", relationship="grandson", ask="bail", amount="$4,000"
    )
    assert ans == "timeout"
    assert room.verification is not None
    assert room.verification.answer == "timeout"
    await ctrl.end_call()


@pytest.mark.asyncio
async def test_tool_handlers_and_blocked_headline():
    hub = RoomHub(verification_timeout_s=2.0)
    room = hub.create_or_get_room("TOOLS1")
    call_id = room.start_new_call()
    ctrl = RoomSessionController(hub=hub, room=room, call_id=call_id)

    async def answer_shortly():
        await asyncio.sleep(0.03)
        ok = await ctrl.submit_verification_answer(None, "denied")
        assert ok is True

    asyncio.create_task(answer_shortly())
    ans = await ctrl.tool_request_family_verification(
        claimed_name="Jake", relationship="grandson", ask="bail", amount="$4,000"
    )
    assert ans == "denied"

    await ctrl.tool_block_call(
        reason="Someone impersonating Jake asked for $4,000",
        scam_type="family_impersonation",
    )
    assert room.state == CallState.BLOCKED
    assert room.last_verdict is not None
    assert (
        room.last_verdict["headline"]
        == "Blocked: someone impersonating Jake asked for $4,000."
    )
    await ctrl.end_call()
    assert room.state == CallState.IDLE
    assert len(room.history) == 1
    assert room.history[0].outcome == "blocked"


@pytest.mark.asyncio
async def test_room_capacity_and_rate_limiter():
    hub = RoomHub(max_rooms=5, rate_limit_per_min=3)
    for i in range(5):
        r = hub.create_or_get_room(f"ACTV0{i}")
        r.start_new_call()

    # All 5 rooms have active calls -> 6th room raises CapacityError
    with pytest.raises(CapacityError):
        hub.create_or_get_room("ACTV06")

    # Mark one room idle -> new room evicts idle room cleanly
    hub.rooms["ACTV00"].active_call_id = None
    hub.rooms["ACTV00"].state = CallState.IDLE
    r6 = hub.create_or_get_room("ACTV06")
    assert r6.code == "ACTV06"
    assert "ACTV00" not in hub.rooms

    limiter = SlidingRateLimiter(max_calls=2, window_seconds=60.0)
    assert limiter.allow("1.2.3.4", now=100.0) is True
    assert limiter.allow("1.2.3.4", now=101.0) is True
    assert limiter.allow("1.2.3.4", now=102.0) is False
    assert limiter.allow("5.6.7.8", now=102.0) is True


def test_pages_and_room_isolation_in_mock_mode(monkeypatch):
    monkeypatch.setenv("VOUCH_MOCK", "1")
    with TestClient(app) as client:
        for path in ("/", "/demo?room=ISOA", "/caller?room=ISOA", "/senior?room=ISOA", "/family?room=ISOA"):
            resp = client.get(path)
            assert resp.status_code == 200

        qr_resp = client.get("/api/qr?url=https://example.com/family?room=ISOA")
        assert qr_resp.status_code == 200
        assert "<svg" in qr_resp.text

        with (
            client.websocket_connect("/ws?room=ISOA&role=caller") as caller_a,
            client.websocket_connect("/ws?room=ISOA&role=senior") as senior_a,
            client.websocket_connect("/ws?room=ISOA&role=family") as family_a,
            client.websocket_connect("/ws?room=ISOB&role=senior") as senior_b,
        ):
            # Drain initial snapshots
            assert caller_a.receive_json()["type"] == "room_snapshot"
            assert senior_a.receive_json()["type"] == "room_snapshot"
            assert family_a.receive_json()["type"] == "room_snapshot"
            assert senior_b.receive_json()["type"] == "room_snapshot"

            # Trigger hero flow in room ISOA via text fallback
            caller_a.send_json(
                {
                    "type": "caller_text",
                    "text": "Grandma, it's Jake. I'm in trouble, I need $4,000 for bail. Please don't tell Mom.",
                }
            )

            ver_req = None
            for _ in range(15):
                ev = family_a.receive_json()
                if ev.get("type") == "verification_requested":
                    ver_req = ev
                    break
            assert ver_req is not None
            assert ver_req["claimed_name"] == "Jake"

            family_a.send_json(
                {
                    "type": "verification_response",
                    "id": ver_req["id"],
                    "answer": "denied",
                }
            )

            blocked_ev = None
            for _ in range(20):
                ev = senior_a.receive_json()
                if ev.get("type") == "call_blocked":
                    blocked_ev = ev
                    break
            assert blocked_ev is not None
            assert "Jake" in blocked_ev["headline"]
            assert "$4,000" in blocked_ev["headline"]

            # Verify Room ISOB received ZERO events from Room ISOA
            senior_b.send_json({"type": "ping"})
            pong = senior_b.receive_json()
            assert pong == {"type": "pong"}


def test_streaming_asr_split_tag_stripping():
    room = Room(code="ASR001")
    room.start_new_call()
    assert room.add_or_merge_transcript("assistant", "<no", final=False) is None
    assert room.add_or_merge_transcript("assistant", " speech>", final=False) is None
    assert room.finalize_speaker_transcript("assistant") is None
    assert room.transcripts == []

    e1 = room.add_or_merge_transcript("assistant", "Jake says he isn't calling. <no", final=False)
    assert e1 is not None and e1.text == "Jake says he isn't calling."
    e2 = room.add_or_merge_transcript("assistant", " speech> Goodbye.", final=False)
    assert e2 is not None and e2.text == "Jake says he isn't calling. Goodbye."
