from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import STATIC_DIR, discover_models, is_mock_mode, is_test_mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vouch.main")


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


@app.get("/api/health")
async def health():
    models = discover_models()
    return {
        "ok": True,
        "mock": is_mock_mode(),
        "test_mode": is_test_mode(),
        "live_model": models.live_model,
        "report_model": models.report_model,
        "report_label": models.report_label,
        "tts_model": models.tts_model,
    }


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
