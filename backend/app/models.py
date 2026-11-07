"""Plain data containers shared across the app. No logic lives here.

ToneSignal, VoiceSignal, RiskState and TimelineEvent are added when the code
that uses them exists.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    # Analysis failed or there is not enough speech yet. Never shown as "safe".
    UNKNOWN = "unknown"


class Persona(str, Enum):
    STANDARD = "standard"
    GRAN = "gran"  # larger text, calmer wording, spoken alerts


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
    # Server clock when the segment arrived; used for latency measurement later.
    received_at: float = field(default_factory=time.monotonic)


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
