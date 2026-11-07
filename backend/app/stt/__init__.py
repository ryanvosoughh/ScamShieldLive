"""Speech-to-text sources, and the one place that decides which one a call uses."""
from __future__ import annotations

from app.config import Settings
from app.stt.base import BYTES_PER_SAMPLE, SAMPLE_RATE, SpeechToTextClient, STTError
from app.stt.deepgram import DeepgramSTT

__all__ = [
    "BYTES_PER_SAMPLE",
    "SAMPLE_RATE",
    "DeepgramSTT",
    "STTError",
    "SpeechToTextClient",
    "make_stt",
]


def make_stt(settings: Settings) -> SpeechToTextClient:
    """Pick the transcription engine for a new call."""
    if settings.demo_mode:
        # ReplaySTT arrives in Phase 2. Until then, say so plainly instead of failing oddly.
        raise STTError(
            "Demo mode (replayed calls, no keys) arrives in Phase 2. "
            "For now set DEMO_MODE=false and add DEEPGRAM_API_KEY to .env."
        )
    return DeepgramSTT(api_key=settings.deepgram_api_key, model=settings.deepgram_model)
