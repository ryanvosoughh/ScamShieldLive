"""The /ws/call WebSocket: one connection is one call.

Messages from the browser:
  binary frame         16 kHz mono 16-bit PCM audio (about 100 ms per frame)
  {"type": "stop"}     the user pressed Stop

Messages to the browser (all JSON):
  {"type": "ready"}                                  transcription is connected; start sending audio
  {"type": "transcript", "text", "is_final", ...}    live text
  {"type": "error", "code", "message"}               something failed; message is user-friendly
  {"type": "ended"}                                  the call is over; the server then closes
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.session import CallSession, SendFn
from app.stt import SAMPLE_RATE, STTError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/call")
async def call_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = websocket.app.state.settings
    stt_factory = websocket.app.state.stt_factory
    send = _make_sender(websocket)

    try:
        session = CallSession(stt=stt_factory(settings), send=send)
        await session.start()
    except STTError as exc:
        await send({"type": "error", "code": "stt_unavailable", "message": str(exc)})
        await _close(websocket)
        return

    await send({"type": "ready", "sample_rate": SAMPLE_RATE})
    try:
        await _receive_until_stop(websocket, session)
    except STTError as exc:
        await send({"type": "error", "code": "stt_failed", "message": str(exc)})
    except Exception:
        logger.exception("Unexpected error during call")
        await send({"type": "error", "code": "server_error", "message": "Something went wrong on the server."})
    finally:
        await session.end()
        await send({"type": "ended"})
        await _close(websocket)


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
