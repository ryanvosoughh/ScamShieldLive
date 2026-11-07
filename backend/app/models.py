"""Plain data containers shared across the app. No logic lives here.

Phase 1 needs only these. TextSignal, ToneSignal, VoiceSignal, RiskState and
TimelineEvent are added in Phase 2 when the code that uses them exists.
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
