"""Plain data containers shared across the app. No logic lives here."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    # Analysis failed or there is not enough speech yet. Never shown as "safe".
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TranscriptSegment:
    """One piece of text from the speech-to-text engine.

    Interim segments (is_final=False) are a running guess that gets replaced;
    final segments are settled text and are what the analyser will read.
    """

    text: str
    is_final: bool
    start: float  # seconds since the call started, on the audio clock
    end: float
    confidence: float  # 0-1, as reported by the engine


@dataclass(frozen=True)
class TextSignal:
    """What the live model made of the recent transcript.

    risk is None when the check failed: that means UNKNOWN, never "safe".
    """

    risk: int | None  # 0-100, or None when unknown
    scam_type: str  # a key from analysis.prompts.SCAM_TYPES, "other", "none", or "unknown"
    evidence: tuple[str, ...] = ()  # phrases copied from the transcript
    red_flags: tuple[str, ...] = ()  # keys from analysis.prompts.RED_FLAGS
    reason: str = ""  # one plain sentence
    next_action: str = ""  # what the person should do now
    error: str | None = None  # why the check failed; for logs, not for the screen

    @property
    def is_unknown(self) -> bool:
        return self.risk is None

    @classmethod
    def unknown(cls, error: str) -> TextSignal:
        return cls(risk=None, scam_type="unknown", error=error)


@dataclass(frozen=True)
class RiskState:
    """What the risk meter shows after each check."""

    level: RiskLevel
    score: float | None  # smoothed 0-100; None while the level is UNKNOWN
    scam_type: str = "unknown"
    reason: str = ""
    next_action: str = ""
    evidence: tuple[str, ...] = ()  # every evidence phrase heard so far in the call
    red_flags: tuple[str, ...] = ()  # every red flag heard so far in the call
    stale: bool = False  # the latest check failed; this is the last good result
    breakdown: tuple[str, ...] = ()  # how the level was reached, from RiskScorer.explain()
