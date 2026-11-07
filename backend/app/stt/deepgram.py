"""Live streaming transcription with Deepgram over a WebSocket.

We talk to Deepgram's WebSocket API directly with the `websockets` library
instead of their SDK: one fewer dependency, and every message is visible here.
API reference: https://developers.deepgram.com/docs/live-streaming-audio
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from app.models import TranscriptSegment
from app.stt.base import SAMPLE_RATE, SpeechToTextClient, STTError

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
# Deepgram closes the stream after ~10 s without data, so send a KeepAlive
# whenever audio has paused this long (for example while a spoken alert plays).
KEEPALIVE_AFTER_SECONDS = 4.0
CLOSE_FLUSH_TIMEOUT_SECONDS = 5.0


class DeepgramSTT(SpeechToTextClient):
    def __init__(self, api_key: str, model: str = "nova-3", language: str = "en") -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._language = language
        self._ws: ClientConnection | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._keepalive: asyncio.Task[None] | None = None
        self._last_audio_at = 0.0
        self._closing = False

    def build_url(self) -> str:
        params = {
            "model": self._model,
            "language": self._language,
            "encoding": "linear16",
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "interim_results": "true",  # fast partial text while the person is still talking
            "smart_format": "true",  # punctuation, numbers as digits
            "endpointing": 300,  # ms of silence before a phrase is finalised
        }
        return f"{DEEPGRAM_URL}?{urlencode(params)}"

    async def connect(self) -> None:
        try:
            self._ws = await connect(
                self.build_url(),
                additional_headers={"Authorization": f"Token {self._api_key}"},
                open_timeout=10,
            )
        except InvalidStatus as exc:
            raise STTError(_describe_http_failure(exc.response.status_code)) from exc
        except (OSError, TimeoutError, InvalidHandshake) as exc:
            raise STTError("Could not reach Deepgram. Check your internet connection.") from exc

        self._last_audio_at = time.monotonic()
        self._receiver = asyncio.create_task(self._receive_loop())
        self._keepalive = asyncio.create_task(self._keepalive_loop())
        logger.info("Connected to Deepgram (model=%s)", self._model)

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None or self._closing:
            raise STTError("The transcription stream is not open.")
        try:
            await self._ws.send(chunk)
        except ConnectionClosed as exc:
            raise STTError("The connection to Deepgram was lost.") from exc
        self._last_audio_at = time.monotonic()

    async def close(self) -> None:
        if self._ws is None or self._closing:
            return
        self._closing = True
        if self._keepalive is not None:
            self._keepalive.cancel()
        try:
            # CloseStream asks Deepgram to finalise any text still in flight, then
            # close from its side; the receive loop ends when that happens.
            await self._ws.send(json.dumps({"type": "CloseStream"}))
        except ConnectionClosed:
            pass
        if self._receiver is not None:
            try:
                await asyncio.wait_for(self._receiver, timeout=CLOSE_FLUSH_TIMEOUT_SECONDS)
            except TimeoutError:
                self._receiver.cancel()
        await self._ws.close()
        self._ws = None
        logger.info("Deepgram stream closed")

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if not isinstance(raw, str):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Ignoring non-JSON message from Deepgram")
                    continue
                segment = parse_message(message)
                if segment is not None:
                    await self._emit_transcript(segment)
        except ConnectionClosed as exc:
            if not self._closing:
                await self._emit_error(_describe_close(exc))
            return
        # The loop also ends on a clean close; that is only expected after CloseStream.
        if not self._closing:
            await self._emit_error("Deepgram ended the transcription stream unexpectedly.")

    async def _keepalive_loop(self) -> None:
        assert self._ws is not None
        while True:
            await asyncio.sleep(1.0)
            if time.monotonic() - self._last_audio_at < KEEPALIVE_AFTER_SECONDS:
                continue
            try:
                await self._ws.send(json.dumps({"type": "KeepAlive"}))
            except ConnectionClosed:
                return
            self._last_audio_at = time.monotonic()


def parse_message(message: dict[str, Any]) -> TranscriptSegment | None:
    """Turn one Deepgram message into a TranscriptSegment, or None if it carries no text.

    Empty *final* results are kept on purpose: they tell the browser to clear the
    grey interim guess when Deepgram decides the sound was not speech.
    """
    if message.get("type") != "Results":
        return None  # Metadata, SpeechStarted, UtteranceEnd: not needed yet
    alternatives = (message.get("channel") or {}).get("alternatives") or []
    if not alternatives:
        return None
    best = alternatives[0]
    text = (best.get("transcript") or "").strip()
    is_final = bool(message.get("is_final"))
    if not text and not is_final:
        return None
    start = float(message.get("start") or 0.0)
    duration = float(message.get("duration") or 0.0)
    return TranscriptSegment(
        text=text,
        is_final=is_final,
        start=start,
        end=start + duration,
        confidence=float(best.get("confidence") or 0.0),
    )


def _describe_http_failure(status: int) -> str:
    if status in (401, 403):
        return "Deepgram rejected the API key. Check DEEPGRAM_API_KEY in .env."
    if status == 402:
        return "The Deepgram account has run out of credit."
    if status == 429:
        return "Deepgram is rate-limiting this account. Wait a moment and try again."
    return f"Deepgram refused the connection (HTTP {status})."


def _describe_close(exc: ConnectionClosed) -> str:
    reason = exc.rcvd.reason if exc.rcvd is not None else ""
    if "NET-0001" in reason:
        return "Deepgram stopped because it received no audio for about 10 seconds."
    if "DATA-0000" in reason:
        return "Deepgram could not decode the audio it was sent."
    suffix = f" ({reason})" if reason else ""
    return f"The connection to Deepgram was lost{suffix}."
