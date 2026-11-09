"""The common interface every speech-to-text source implements.

CallSession only talks to this interface, so the live engine (DeepgramSTT) and
the keyless demo engine (ReplaySTT) are interchangeable.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from app.models import TranscriptSegment

TranscriptCallback = Callable[[TranscriptSegment], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]
NoticeCallback = Callable[[str, "str | None"], Awaitable[None]]

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
        self._notice_callback: NoticeCallback | None = None
        # Set by a source that ends on its own (a replayed demo call). A live
        # call never sets it: it ends when the person presses Stop.
        self.finished = asyncio.Event()

    def on_transcript(self, callback: TranscriptCallback) -> None:
        """Register who receives each transcript segment."""
        self._transcript_callback = callback

    def on_error(self, callback: ErrorCallback) -> None:
        """Register who hears about failures that happen mid-stream.

        Not in the original plan's interface: errors that arrive on the engine's
        own background connection have no caller to raise into, so they need a callback.
        """
        self._error_callback = callback

    def on_notice(self, callback: NoticeCallback) -> None:
        """Register who hears about problems that don't stop the call.

        The callback gets a code and a user-friendly message, or the code and
        None when the problem has gone away (e.g. "no words recognised").
        """
        self._notice_callback = callback

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

    async def _emit_notice(self, code: str, message: str | None) -> None:
        logger.info("STT notice %s: %s", code, message or "cleared")
        if self._notice_callback is not None:
            await self._notice_callback(code, message)
