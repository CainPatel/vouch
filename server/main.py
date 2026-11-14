from __future__ import annotations

import io
import json
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse, urlunparse

import segno
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from server.config import (
    STATIC_DIR,
    discover_models,
    is_mock_mode,
    is_test_mode,
    resolve_public_origin,
)
from server.hub import CapacityError, RateLimitError, RoomHub

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vouch.main")

hub = RoomHub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    models = discover_models()
    logger.info(
        "Vouch starting (mock=%s, test_mode=%s, live_model=%s, report_model=%s)",
        is_mock_mode(),
        is_test_mode(),
        models.live_model,
        models.report_model,
    )
    yield


app = FastAPI(title="Vouch", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _client_ip(request_or_ws: Request | WebSocket) -> str:
    xff = request_or_ws.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    if request_or_ws.client and request_or_ws.client.host:
        return request_or_ws.client.host
    return "127.0.0.1"


def _public_origin(request_or_ws: Request | WebSocket) -> str:
    scheme = (
        request_or_ws.headers.get("x-forwarded-proto", "")
        or getattr(request_or_ws.url, "scheme", "http")
        or "http"
    ).split(",")[0].strip()
    if scheme in ("ws", "wss"):
        scheme = "https" if scheme == "wss" else "http"
    host = (
        request_or_ws.headers.get("x-forwarded-host", "")
        or request_or_ws.headers.get("host", "")
        or "localhost:8080"
    )
    return resolve_public_origin(host_header=host, scheme=scheme)


@app.get("/api/health")
async def health(request: Request):
    models = discover_models()
    return {
        "ok": True,
        "mock": is_mock_mode(),
        "test_mode": is_test_mode(),
        "live_model": models.live_model,
        "report_model": models.report_model,
        "report_label": models.report_label,
        "tts_model": models.tts_model,
        "active_rooms": len(hub.rooms),
        "public_origin": _public_origin(request),
    }


@app.post("/api/rooms")
async def create_room():
    try:
        room = hub.create_or_get_room()
        return {"room": room.code}
    except CapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.get("/api/qr")
async def qr_svg(
    request: Request,
    url: str = Query(..., min_length=1, max_length=512),
):
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        origin = urlparse(_public_origin(request))
        if origin.scheme and origin.netloc:
            url = urlunparse(
                (
                    origin.scheme,
                    origin.netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )

    qr = segno.make(url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", omitsize=True, border=4, dark="#0f172a", light="#ffffff")
    svg_text = buf.getvalue().decode("utf-8").replace(
        "<svg ",
        '<svg width="256" height="256" shape-rendering="crispEdges" ',
        1,
    )
    return Response(
        content=svg_text.encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/demo")
async def demo_page(room: str | None = None):
    if not room:
        try:
            created = hub.create_or_get_room()
        except CapacityError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return RedirectResponse(url=f"/demo?room={created.code}", status_code=307)
    try:
        hub.create_or_get_room(room)
    except CapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return FileResponse(STATIC_DIR / "demo.html")


@app.get("/caller")
async def caller_page(room: str | None = None):
    if not room:
        try:
            target = hub.latest_or_create_room()
        except CapacityError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return RedirectResponse(url=f"/caller?room={target.code}", status_code=307)
    return FileResponse(STATIC_DIR / "caller.html")


@app.get("/senior")
async def senior_page(room: str | None = None):
    if not room:
        try:
            target = hub.latest_or_create_room()
        except CapacityError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return RedirectResponse(url=f"/senior?room={target.code}", status_code=307)
    return FileResponse(STATIC_DIR / "senior.html")


@app.get("/family")
async def family_page(room: str | None = None):
    if not room:
        try:
            target = hub.latest_or_create_room()
        except CapacityError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return RedirectResponse(url=f"/family?room={target.code}", status_code=307)
    return FileResponse(STATIC_DIR / "family.html")


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    room: str = Query(...),
    role: str = Query("demo"),
):
    if role not in ("caller", "senior", "family", "demo"):
        await websocket.close(code=1008, reason="Invalid role")
        return

    client_ip = _client_ip(websocket)
    await websocket.accept()

    try:
        room_obj = hub.register_client(room, websocket, role, client_ip)
    except CapacityError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1013, reason="Room capacity reached")
        return

    models = discover_models()
    snap = room_obj.snapshot()
    snap["live_model"] = models.live_model
    snap["report_label"] = f"Report by {models.report_label}"
    snap["mock"] = is_mock_mode()
    snap["public_origin"] = _public_origin(websocket)
    await websocket.send_json(snap)

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if msg.get("bytes") is not None:
                if role == "caller":
                    ctrl = hub.controllers.get(room_obj.code)
                    if ctrl:
                        await ctrl.handle_caller_audio(msg["bytes"])
                continue

            text_payload = msg.get("text")
            if not text_payload:
                continue

            try:
                data = json.loads(text_payload)
            except json.JSONDecodeError:
                continue

            ev_type = data.get("type")
            if ev_type == "start_call":
                try:
                    await hub.start_call(room_obj.code, client_ip=client_ip)
                except (RateLimitError, CapacityError) as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
            elif ev_type == "end_call":
                await hub.end_call(room_obj.code, reason="Call ended")
            elif ev_type == "caller_text":
                ctrl = hub.controllers.get(room_obj.code)
                if not ctrl or ctrl._closed:
                    try:
                        ctrl = await hub.start_call(room_obj.code, client_ip=client_ip)
                    except (RateLimitError, CapacityError) as exc:
                        await websocket.send_json({"type": "error", "message": str(exc)})
                        continue
                await ctrl.handle_caller_text(str(data.get("text", "")))
            elif ev_type == "caller_speech_end":
                ctrl = hub.controllers.get(room_obj.code)
                if ctrl and not ctrl._closed:
                    ctrl.mark_caller_speech_end()
            elif ev_type == "verification_response":
                ctrl = hub.controllers.get(room_obj.code)
                if ctrl and not ctrl._closed:
                    await ctrl.submit_verification_answer(
                        ver_id=data.get("id"),
                        answer=str(data.get("answer", "")),
                    )
            elif ev_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister_client(room_obj.code, websocket)
        if role == "caller":
            # Only auto-end if no other caller WS remains in this room
            remaining_callers = [
                c for c in hub.clients.get(room_obj.code, []) if c.role == "caller"
            ]
            if not remaining_callers:
                await hub.end_call(room_obj.code, reason="Caller disconnected")
