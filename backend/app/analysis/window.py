"""TranscriptWindow: the recent settled text the analyser reads.

Only final segments go in; interim text is a guess that keeps changing, and
analysing it would waste model calls on words that are about to be replaced.

Times are on the audio clock (seconds since the call started, as reported by
the speech-to-text engine), not the server clock. That keeps the window the
same whether audio comes from the mic, a file, or a replayed demo script, and
makes it easy to test.
"""
from __future__ import annotations

from app.models import TranscriptSegment

# Below this many words there is not enough to judge ("Hello?", "Yes, speaking."),
# so the analyser is not called. Saves model calls on the free tier.
DEFAULT_MIN_WORDS = 6


class TranscriptWindow:
    def __init__(self, window_seconds: float = 30.0, min_words: int = DEFAULT_MIN_WORDS) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than 0")
        if min_words < 1:
            raise ValueError("min_words must be at least 1")
        self.window_seconds = window_seconds
        self.min_words = min_words
        # Every final segment of the call, oldest first. A call's text is small,
        # so nothing is thrown away; text() picks out the recent part.
        self._segments: list[TranscriptSegment] = []

    def add(self, segment: TranscriptSegment) -> bool:
        """Store a final segment. Returns True if it was stored.

        Interim segments and empty finals (Deepgram sends these to clear the
        interim line) are ignored.
        """
        if not segment.is_final or not segment.text.strip():
            return False
        self._segments.append(segment)
        return True

    def text(self, last_seconds: float | None = None, now: float | None = None) -> str:
        """The text spoken in the last `last_seconds` (default: the window size).

        `now` is the current point on the audio clock. If not given, the end of
        the newest segment is used. A segment that started before the cut-off
        but ends after it is kept whole, so sentences are never cut in half.
        """
        return " ".join(s.text.strip() for s in self._recent(last_seconds, now))

    def has_enough_content(self, now: float | None = None) -> bool:
        """True when the window holds at least `min_words` words."""
        return len(self.text(now=now).split()) >= self.min_words

    def _recent(self, last_seconds: float | None, now: float | None) -> list[TranscriptSegment]:
        if not self._segments:
            return []
        span = self.window_seconds if last_seconds is None else last_seconds
        reference = self._segments[-1].end if now is None else now
        cutoff = reference - span

        recent: list[TranscriptSegment] = []
        # Walk back from the newest segment and stop at the first one that
        # ended before the cut-off; everything older ended earlier still.
        for segment in reversed(self._segments):
            if segment.end <= cutoff:
                break
            recent.append(segment)
        recent.reverse()
        return recent
