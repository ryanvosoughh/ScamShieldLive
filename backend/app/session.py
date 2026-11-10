"""CallSession: orchestrates one call. Everything is in memory and gone when the call ends.

Browser audio goes to speech-to-text, and the text comes back to the browser.
Final text also goes into the transcript window; after new speech, the scam
check runs on the window, the scorer turns the result into a level, the alert
policy picks the meter's headline and whether to say a warning out loud, and
the new state goes to the browser.

When checks run (Groq's free tier allows about 8,000 tokens a minute, and a
check is about 1,350):
  - only after new final speech, so silence costs nothing;
  - at least check_interval seconds apart (ANALYSIS_INTERVAL_SECONDS, 4 s);
  - at most checks_per_minute in any 60 s (CHECKS_PER_MINUTE, 5). So the start
    of a call, where a warning matters most, is checked every 4 s, and a long
    call settles to about one check every 12 s;
  - one at a time: speech that arrives during a check waits for the next one.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from app.alerts import Alert, AlertPolicy, lines_for
from app.analysis import ScamAnalyzer, TranscriptWindow
from app.models import RiskState, TextSignal, TranscriptSegment
from app.scoring import RiskScorer
from app.stt import BYTES_PER_SAMPLE, SAMPLE_RATE, SpeechToTextClient

logger = logging.getLogger(__name__)

SendFn = Callable[[dict[str, Any]], Awaitable[None]]

# 100 ms of audio is 3,200 bytes; anything far bigger than a second is not a
# real-time stream, so it is dropped rather than forwarded.
MAX_CHUNK_BYTES = 64 * 1024
DEFAULT_CHECK_INTERVAL_SECONDS = 4.0
DEFAULT_CHECKS_PER_MINUTE = 5

# A single failed check (one rate-limit blip) only shows on the risk meter. Two
# in a row is more likely a real outage, so the page also gets a banner.
FAILURES_BEFORE_NOTICE = 2
ANALYSIS_DOWN_CODE = "analysis_unavailable"
ANALYSIS_DOWN_MESSAGE = (
    "The scam check isn't answering, so warnings may be late or missing. "
    "The words are still being written out, and checks carry on as soon as it answers."
)


class CallSession:
    def __init__(
        self,
        stt: SpeechToTextClient,
        send: SendFn,
        analyzer: ScamAnalyzer | None = None,
        scorer: RiskScorer | None = None,
        window: TranscriptWindow | None = None,
        check_interval: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        checks_per_minute: int = DEFAULT_CHECKS_PER_MINUTE,
        rate_window_seconds: float = 60.0,  # the "minute"; shorter only in tests
        alerts: AlertPolicy | None = None,
    ) -> None:
        self._stt = stt
        self._send = send  # delivers one JSON message to the browser
        self._analyzer = analyzer  # None: no Groq key, so no scam checks
        self.scorer = scorer or RiskScorer()
        self.window = window or TranscriptWindow()
        self.alerts = alerts or AlertPolicy()  # the meter's headline, and when to speak
        self.check_interval = check_interval
        self.checks_per_minute = checks_per_minute
        self.rate_window_seconds = rate_window_seconds
        self._ended = False
        self.started_at: float | None = None
        self.audio_bytes = 0
        self.checks = 0  # scam checks run in this call

        self._new_speech = asyncio.Event()  # set when final text arrives
        self._check_lock = asyncio.Lock()  # never two checks at once
        self._check_times: deque[float] = deque()  # starts of recent checks, oldest first
        self._checks_task: asyncio.Task | None = None
        self._failures_in_a_row = 0
        self._analysis_notice_up = False

        stt.on_transcript(self.on_transcript)
        stt.on_error(self._on_stt_error)
        stt.on_notice(self._send_notice)

    @property
    def audio_seconds(self) -> float:
        """How much call audio has arrived so far, on the audio clock."""
        return self.audio_bytes / (SAMPLE_RATE * BYTES_PER_SAMPLE)

    @property
    def analysis_on(self) -> bool:
        return self._analyzer is not None

    async def start(self) -> None:
        await self._stt.connect()
        self.started_at = time.monotonic()
        if self._analyzer is not None:
            self._checks_task = asyncio.create_task(self._run_checks(), name="scam-checks")

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
        if self.window.add(segment):
            self._new_speech.set()  # 2.31: new final text wakes the check loop

    async def tick(self) -> RiskState | None:
        """2.30: one scam check of the recent speech. Returns the new state, or None if skipped."""
        if self._analyzer is None or self._ended:
            return None
        async with self._check_lock:
            if not self.window.has_enough_content():
                return None  # e.g. just "Hello?": not worth a model call
            started = time.monotonic()
            self._check_times.append(started)
            signal = await self._analyzer.analyze(self.window.text())
            state = self.scorer.update(text=signal)
            self.checks += 1
            took = time.monotonic() - started
            logger.info(
                "Check %d: %s, score %s, in %.1f s%s",
                self.checks,
                state.level.value,
                "n/a" if state.score is None else f"{state.score:.0f}",
                took,
                f" ({signal.error})" if signal.error else "",
            )
            alert = self.alerts.decide(state)
            if alert.spoken:
                logger.info("Speaking the %s alert", alert.level.value)
            await self._send(state_message(state, alert))  # 2.32
            await self._track_failures(signal)
            return state

    async def end(self) -> None:
        """Finish the call. Safe to call more than once."""
        if self._ended:
            return
        self._ended = True
        if self._checks_task is not None:
            self._checks_task.cancel()  # also cancels a check that is in flight
            with contextlib.suppress(asyncio.CancelledError):
                await self._checks_task
        await self._stt.close()
        logger.info("Call ended after %.1f s of audio and %d scam checks", self.audio_seconds, self.checks)

    async def _run_checks(self) -> None:
        """Wait for new speech, then for a free slot, then check."""
        while True:
            await self._new_speech.wait()
            wait = self._seconds_until_next_slot()
            if wait > 0:
                await asyncio.sleep(wait)
            # Speech that arrives from here on waits for the next check.
            self._new_speech.clear()
            try:
                await self.tick()
            except Exception:  # keep checking for the rest of the call
                logger.exception("Scam check loop error")

    def _seconds_until_next_slot(self) -> float:
        """How long until a check is allowed by both the gap and the per-minute cap."""
        now = time.monotonic()
        while self._check_times and now - self._check_times[0] >= self.rate_window_seconds:
            self._check_times.popleft()  # older than a minute: no longer counts
        if not self._check_times:
            return 0.0
        wait = self._check_times[-1] + self.check_interval - now
        if len(self._check_times) >= self.checks_per_minute:
            # Wait until the oldest check in the window is a minute old.
            wait = max(wait, self._check_times[0] + self.rate_window_seconds - now)
        return max(0.0, wait)

    async def _track_failures(self, signal: TextSignal) -> None:
        """Banner when the scam check keeps failing; take it down when a check answers."""
        if not signal.is_unknown:
            self._failures_in_a_row = 0
            if self._analysis_notice_up:
                self._analysis_notice_up = False
                await self._send_notice(ANALYSIS_DOWN_CODE, None)
            return
        self._failures_in_a_row += 1
        if self._failures_in_a_row >= FAILURES_BEFORE_NOTICE and not self._analysis_notice_up:
            self._analysis_notice_up = True
            detail = f" ({signal.error})" if signal.error else ""
            await self._send_notice(ANALYSIS_DOWN_CODE, ANALYSIS_DOWN_MESSAGE + detail)

    async def _send_notice(self, code: str, message: str | None) -> None:
        """A problem that doesn't stop the call. message=None takes the notice down again."""
        await self._send({"type": "notice", "code": code, "message": message})

    async def _on_stt_error(self, message: str) -> None:
        await self._send({"type": "error", "code": "stt_failed", "message": message})


def state_message(state: RiskState, alert: Alert | None = None) -> dict[str, Any]:
    """The JSON the browser gets after each check, in plain JSON types.

    headline is the meter's title; speak is the line to say out loud now, or None.
    """
    message: dict[str, Any] = {"type": "state"}
    for key, value in asdict(state).items():
        message[key] = list(value) if isinstance(value, tuple) else value
    message["level"] = state.level.value
    message["headline"] = alert.screen if alert else lines_for(state.level).screen
    message["speak"] = alert.spoken if alert else None
    return message
