"""Speech-to-text sources, and the one place that decides which one a live call uses."""
from __future__ import annotations

from app.config import Settings
from app.stt.base import BYTES_PER_SAMPLE, SAMPLE_RATE, SpeechToTextClient, STTError
from app.stt.deepgram import DeepgramSTT
from app.stt.replay import ReplaySTT

__all__ = [
    "BYTES_PER_SAMPLE",
    "SAMPLE_RATE",
    "DeepgramSTT",
    "ReplaySTT",
    "STTError",
    "SpeechToTextClient",
    "make_stt",
]


def make_stt(settings: Settings) -> SpeechToTextClient:
    """The engine for a live (microphone or audio file) call. Demo calls use ReplaySTT instead."""
    return DeepgramSTT(api_key=settings.deepgram_api_key, model=settings.deepgram_model)
