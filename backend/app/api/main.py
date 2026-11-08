"""FastAPI app: /health, the /ws/call WebSocket, and the static frontend.

Built by a factory (create_app) so importing this module has no side effects,
and tests can pass in their own settings, a fake speech-to-text engine and a
fake scam analyser.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.analysis import ScamAnalyzer
from app.api.ws import router as ws_router
from app.config import PROJECT_ROOT, Settings, load_or_exit
from app.stt import make_stt

FRONTEND_DIR = PROJECT_ROOT / "frontend"


def create_app(
    settings: Settings | None = None,
    stt_factory=make_stt,
    analyzer_factory=ScamAnalyzer.from_settings,
) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s")
    settings = settings or load_or_exit()

    app = FastAPI(title="ScamShield Live", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.stt_factory = stt_factory
    # One analyser for the whole app, so calls reuse its connection to Groq.
    app.state.analyzer = analyzer_factory(settings)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "mode": "demo" if settings.demo_mode else "live",
            "keys": {
                "deepgram": bool(settings.deepgram_api_key),
                "groq": bool(settings.groq_api_key),
            },
        }

    app.include_router(ws_router)
    # Mounted last so /health and /ws/call take priority over static files.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
