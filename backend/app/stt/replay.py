"""ReplaySTT: plays a scripted demo call as if it were being transcribed live.

Each line comes out the way Deepgram sends real speech: a few interim words
at a time while the line is "spoken", then the final line at its end time.
No audio, no network, no keys. When the script is over (plus a little quiet
time) it sets `finished`, and the call ends by itself.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from app.demo.scenarios import Line, Scenario
from app.models import TranscriptSegment
from app.stt.base import SpeechToTextClient

logger = logging.getLogger(__name__)

INTERIM_UPDATES_PER_LINE = 3  # grey "still listening" updates before each final line


class ReplaySTT(SpeechToTextClient):
    def __init__(self, scenario: Scenario, speed: float = 1.0) -> None:
        super().__init__()
        if speed <= 0:
            raise ValueError("speed must be greater than 0")
        self.scenario = scenario
        self.speed = speed  # 1.0 is real time; tests play faster
        self._task: asyncio.Task | None = None
        self._started_at = 0.0

    async def connect(self) -> None:
        self._started_at = time.monotonic()
        self._task = asyncio.create_task(self._play(), name=f"replay-{self.scenario.id}")

    async def send_audio(self, chunk: bytes) -> None:
        """A replayed call brings its own words, so any audio is ignored."""

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _play(self) -> None:
        try:
            for line in self.scenario.lines:
                await self._speak(line)
            await self._wait_until(self.scenario.duration)
            self.finished.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Demo replay failed")
            await self._emit_error("The demo call stopped unexpectedly.")
            self.finished.set()

    async def _speak(self, line: Line) -> None:
        words = line.text.split()
        for step in range(1, INTERIM_UPDATES_PER_LINE + 1):
            count = len(words) * step // (INTERIM_UPDATES_PER_LINE + 1)
            if count == 0:
                continue
            at = line.start + (line.end - line.start) * step / (INTERIM_UPDATES_PER_LINE + 1)
            await self._wait_until(at)
            await self._emit_transcript(TranscriptSegment(" ".join(words[:count]), False, line.start, at, 0.8))
        await self._wait_until(line.end)
        await self._emit_transcript(TranscriptSegment(line.text, True, line.start, line.end, 0.99))

    async def _wait_until(self, call_seconds: float) -> None:
        """Sleep until this point in the call, on the replay clock."""
        delay = self._started_at + call_seconds / self.speed - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
