"""Plain data containers shared across the app. No logic lives here.

Phase 1 uses TranscriptSegment only. The signal and risk types are defined now
so later phases plug into a shape that is already agreed; expect small changes.
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


class ScamType(str, Enum):
    GRANDCHILD = "grandchild_in_trouble"
    BANK = "bank_impersonation"
    TECH_SUPPORT = "tech_support"
    ROMANCE = "romance"
    PRIZE = "prize"
    OTHER = "other"
    NONE = "none"


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
    """What Claude concluded from the recent transcript (Phase 2)."""

    ok: bool  # False when analysis failed: the scorer must treat this as UNKNOWN
    risk: int | None  # 0-100
    scam_type: ScamType
    evidence: list[str]  # exact phrases from the transcript, for highlighting
    reason: str
    next_action: str


@dataclass(frozen=True)
class ToneSignal:
    """Urgency cues measured from the audio itself (Phase 3). Low weight only."""

    speech_rate_wps: float | None  # words per second
    loudness_db: float | None
    urgency: float  # 0-1


@dataclass(frozen=True)
class VoiceSignal:
    """Experimental synthetic-voice check (bonus). None means UNCERTAIN."""

    synthetic_score: float | None
    note: str


@dataclass(frozen=True)
class RiskState:
    """The combined verdict the UI shows."""

    level: RiskLevel
    score: float | None
    reason: str
    next_action: str
    evidence: list[str] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=dict)  # per-signal share of the score
    disagreements: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineEvent:
    """One point on the after-call timeline."""

    t: float  # seconds since the call started
    level: RiskLevel
    score: float | None
    reason: str
