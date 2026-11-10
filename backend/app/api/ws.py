"""The /ws/call WebSocket: one connection is one call.

    /ws/call                      a live call: the browser streams audio
    /ws/call?scenario=bank_scam   a scripted demo call: no audio, no keys needed
                                  (with DEMO_MODE=true every call is a demo call)

Messages from the browser:
  binary frame         16 kHz mono 16-bit PCM audio (about 100 ms per frame)
  {"type": "stop"}     the user pressed Stop

Messages to the browser (all JSON):
  {"type": "ready", "analysis", "demo"}              transcription is connected; start sending audio.
                                                     analysis is false when there is no Groq key;
                                                     demo describes the scripted call, or is null
  {"type": "transcript", "text", "is_final", ...}    live text
  {"type": "state", "level", "score", "reason", ...} the risk meter, after each scam check, with
                                                     "headline" for its title and "speak", the
                                                     warning to say out loud now (or null)
  {"type": "notice", "code", "message"}              a problem that doesn't stop the call, e.g. the
                                                     scam check isn't answering; message null
                                                     takes it down again
  {"type": "error", "code", "message"}               something failed; message is user-friendly
  {"type": "ended"}                                  the call is over (Stop, or the demo script
                                                     finished); the server then closes
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.analysis import TranscriptWindow
from app.demo import DEFAULT_SCENARIO, DemoError, ScriptedAnalyzer, load_scenario
from app.scoring import RiskScorer
from app.session import CallSession, SendFn
from app.stt import SAMPLE_RATE, ReplaySTT, STTError

# Scripted verdicts cost nothing, so a keyless demo isn't held to Groq's per-minute cap.
UNLIMITED_CHECKS = 1_000

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/call")
async def call_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    state = websocket.app.state
    settings = state.settings
    send = _make_sender(websocket)
    analyzer = state.analyzer  # shared by all calls; None without a Groq key
    checks_per_minute = settings.checks_per_minute
    demo = None

    try:
        scenario_id = websocket.query_params.get("scenario") or (DEFAULT_SCENARIO if settings.demo_mode else None)
        if scenario_id:
            scenario = load_scenario(scenario_id)
            stt = ReplaySTT(scenario, speed=state.demo_speed)
            scripted = analyzer is None
            if scripted:
                analyzer = ScriptedAnalyzer(scenario)
                checks_per_minute = UNLIMITED_CHECKS
            demo = {"scenario": scenario.id, "title": scenario.title, "scripted_analysis": scripted}
        else:
            stt = state.stt_factory(settings)
        session = CallSession(
            stt=stt,
            send=send,
            analyzer=analyzer,
            scorer=RiskScorer.from_settings(settings),
            window=TranscriptWindow(window_seconds=settings.window_seconds),
            check_interval=settings.analysis_interval_seconds,
            checks_per_minute=checks_per_minute,
        )
        await session.start()
    except DemoError as exc:
        await send({"type": "error", "code": "unknown_scenario", "message": str(exc)})
        await _close(websocket)
        return
    except STTError as exc:
        await send({"type": "error", "code": "stt_unavailable", "message": str(exc)})
        await _close(websocket)
        return

    await send({"type": "ready", "sample_rate": SAMPLE_RATE, "analysis": session.analysis_on, "demo": demo})
    try:
        await _run_until_done(websocket, session, stt)
    except STTError as exc:
        await send({"type": "error", "code": "stt_failed", "message": str(exc)})
    except Exception:
        logger.exception("Unexpected error during call")
        await send({"type": "error", "code": "server_error", "message": "Something went wrong on the server."})
    finally:
        await session.end()
        await send({"type": "ended"})
        await _close(websocket)


async def _run_until_done(websocket: WebSocket, session: CallSession, stt) -> None:
    """Run until the browser says stop or disconnects, or a demo script finishes."""
    browser = asyncio.create_task(_receive_until_stop(websocket, session))
    script_over = asyncio.create_task(stt.finished.wait())
    try:
        done, _ = await asyncio.wait({browser, script_over}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (browser, script_over):
            task.cancel()
        await asyncio.gather(browser, script_over, return_exceptions=True)
    if browser in done:
        browser.result()  # passes on an STTError or a crash to the caller


async def _receive_until_stop(websocket: WebSocket, session: CallSession) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return  # browser closed the tab or lost its connection
        audio = message.get("bytes")
        if audio is not None:
            await session.handle_audio(audio)
            continue
        text = message.get("text")
        if text and _parse_control(text).get("type") == "stop":
            return


def _parse_control(text: str) -> dict[str, Any]:
    try:
        control = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return control if isinstance(control, dict) else {}


def _make_sender(websocket: WebSocket) -> SendFn:
    """A send function that is safe to call from several tasks and after the browser has gone."""
    lock = asyncio.Lock()

    async def send(message: dict[str, Any]) -> None:
        async with lock:
            if websocket.application_state != WebSocketState.CONNECTED:
                return
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                pass  # browser already gone; nothing useful to do

    return send


async def _close(websocket: WebSocket) -> None:
    if websocket.application_state == WebSocketState.CONNECTED:
        try:
            await websocket.close()
        except RuntimeError:
            pass
