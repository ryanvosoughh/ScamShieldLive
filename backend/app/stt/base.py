"""The common interface every speech-to-text source implements.

CallSession only talks to this interface, so the live engine (DeepgramSTT) and
the keyless demo engine (ReplaySTT, Phase 2) are interchangeable.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from app.models import TranscriptSegment

TranscriptCallback = Callable[[TranscriptSegment], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]

logger = logging.getLogger(__name__)

# Audio format the whole app agrees on: 16 kHz, mono, 16-bit little-endian PCM.
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2


class STTError(Exception):
    """A speech-to-text failure. The message is safe to show to the user."""


class SpeechToTextClient(ABC):
    def __init__(self) -> None:
        self._transcript_callback: TranscriptCallback | None = None
        self._error_callback: ErrorCallback | None = None

    def on_transcript(self, callback: TranscriptCallback) -> None:
        """Register who receives each transcript segment."""
        self._transcript_callback = callback

    def on_error(self, callback: ErrorCallback) -> None:
        """Register who hears about failures that happen mid-stream.

        Not in the original plan's interface: errors that arrive on the engine's
        own background connection have no caller to raise into, so they need a callback.
        """
        self._error_callback = callback

    @abstractmethod
    async def connect(self) -> None:
        """Open the stream. Raises STTError with a friendly message on failure."""

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Send one chunk of 16 kHz mono 16-bit PCM. Raises STTError if the stream is gone."""

    @abstractmethod
    async def close(self) -> None:
        """Flush any remaining text, then close. Safe to call more than once."""

    async def _emit_transcript(self, segment: TranscriptSegment) -> None:
        if self._transcript_callback is not None:
            await self._transcript_callback(segment)

    async def _emit_error(self, message: str) -> None:
        logger.warning("STT error: %s", message)
        if self._error_callback is not None:
            await self._error_callback(message)
