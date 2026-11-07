"""CallSession: orchestrates one call. Everything is in memory and gone when the call ends.

Phase 1 is a straight pipe: browser audio goes to speech-to-text, and the text
comes back to the browser. Later phases add tick() (analysis every ~4 s),
scoring and alerts here, without the WebSocket code needing to change.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.models import TranscriptSegment
from app.stt import BYTES_PER_SAMPLE, SAMPLE_RATE, SpeechToTextClient

logger = logging.getLogger(__name__)

SendFn = Callable[[dict[str, Any]], Awaitable[None]]

# 100 ms of audio is 3,200 bytes; anything far bigger than a second is not a
# real-time stream, so it is dropped rather than forwarded.
MAX_CHUNK_BYTES = 64 * 1024


class CallSession:
    def __init__(self, stt: SpeechToTextClient, send: SendFn) -> None:
        self._stt = stt
        self._send = send  # delivers one JSON message to the browser
        self._ended = False
        self.started_at: float | None = None
        self.audio_bytes = 0
        stt.on_transcript(self.on_transcript)
        stt.on_error(self._on_stt_error)

    @property
    def audio_seconds(self) -> float:
        """How much call audio has arrived so far, on the audio clock."""
        return self.audio_bytes / (SAMPLE_RATE * BYTES_PER_SAMPLE)

    async def start(self) -> None:
        await self._stt.connect()
        self.started_at = time.monotonic()

    async def handle_audio(self, chunk: bytes) -> None:
        if self._ended:
            return
        if not chunk or len(chunk) % BYTES_PER_SAMPLE or len(chunk) > MAX_CHUNK_BYTES:
            logger.warning("Dropping malformed audio chunk (%d bytes)", len(chunk))
            return
        self.audio_bytes += len(chunk)
        await self._stt.send_audio(chunk)

    async def on_transcript(self, segment: TranscriptSegment) -> None:
        if segment.is_final and segment.text:
            # How far the text trails the audio we have received. Excludes the
            # browser-to-server hop; the page shows the end-to-end figure.
            logger.debug("final %.2fs behind audio: %s", self.audio_seconds - segment.end, segment.text)
        await self._send(
            {
                "type": "transcript",
                "text": segment.text,
                "is_final": segment.is_final,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "confidence": round(segment.confidence, 3),
            }
        )

    async def end(self) -> None:
        """Finish the call. Safe to call more than once."""
        if self._ended:
            return
        self._ended = True
        await self._stt.close()
        logger.info("Call ended after %.1f s of audio", self.audio_seconds)

    async def _on_stt_error(self, message: str) -> None:
        await self._send({"type": "error", "code": "stt_failed", "message": message})
