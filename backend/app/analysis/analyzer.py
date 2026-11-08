"""ScamAnalyzer: asks the live model whether the recent transcript sounds like a scam.

Every failure (timeout, network, rate limit, a reply that doesn't fit the
answer format) ends as an UNKNOWN signal. Nothing here ever turns a failure
into "safe".

The model is good at spotting what was asked for ("read me the code") but
tends to score calm, polite calls too low. So it also reports which red flags
it heard, and any red flag keeps the risk at or above the red threshold: a
pleasant tone can't talk the score down.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import groq

from app.analysis.prompts import NO_SCAM, OTHER_SCAM, OUTPUT_SCHEMA, RED_FLAGS, build_prompt
from app.config import Settings
from app.models import TextSignal

logger = logging.getLogger(__name__)

# Groq usually answers in under a second; past this, the call is treated as failed.
DEFAULT_TIMEOUT_SECONDS = 4.0
# The answer is about 130 tokens. The cap keeps a runaway reply from eating the
# free tier's per-minute token budget.
MAX_COMPLETION_TOKENS = 600
MAX_EVIDENCE = 3
MAX_TEXT_CHARS = 300  # longest reason or next action shown on screen
# Lowest risk when any red flag is heard. from_settings() uses the red threshold.
DEFAULT_RED_FLAG_FLOOR = 70

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "scam_check", "strict": True, "schema": OUTPUT_SCHEMA},
}
ALLOWED_SCAM_TYPES = frozenset(OUTPUT_SCHEMA["properties"]["scam_type"]["enum"])

# Failures where asking again straight away can't help. A rate limit clears in
# its own time (and the next tick will try anyway); the others need a fix.
_NOT_WORTH_RETRYING = (
    groq.RateLimitError,
    groq.AuthenticationError,
    groq.PermissionDeniedError,
    groq.BadRequestError,
    groq.NotFoundError,
)


class InvalidReply(Exception):
    """The model answered, but not with a usable verdict."""


class ScamAnalyzer:
    def __init__(
        self,
        client: Any,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = 1,
        red_flag_floor: int = DEFAULT_RED_FLAG_FLOOR,
    ) -> None:
        self._client = client  # groq.AsyncGroq, or a fake in tests
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.red_flag_floor = red_flag_floor

    @classmethod
    def from_settings(cls, settings: Settings) -> ScamAnalyzer | None:
        """The live analyser, or None when there is no Groq key."""
        if not settings.groq_api_key:
            return None
        # The SDK's own retries are turned off: analyze() decides when to retry.
        client = groq.AsyncGroq(api_key=settings.groq_api_key, max_retries=0)
        return cls(client, settings.live_model, red_flag_floor=settings.risk_red_threshold)

    async def analyze(self, window_text: str) -> TextSignal:
        """Check the transcript once, retrying once if the first try fails."""
        messages = build_prompt(window_text)
        error = "not run"
        for attempt in range(1, self.retries + 2):
            try:
                raw = await asyncio.wait_for(self._ask(messages), self.timeout_seconds)
                return parse_reply(raw, window_text, self.red_flag_floor)
            except TimeoutError:
                error = f"timed out after {self.timeout_seconds:g} s"
            except _NOT_WORTH_RETRYING as exc:
                return _unknown(_describe(exc))
            except (groq.APIError, InvalidReply) as exc:  # network, server error, bad reply
                error = _describe(exc)
            except Exception as exc:  # a bug or an odd reply shape: still never "safe"
                logger.exception("Scam check failed unexpectedly")
                return _unknown(f"unexpected {type(exc).__name__}")
            logger.warning("Scam check attempt %d failed: %s", attempt, error)
        return _unknown(error)

    async def _ask(self, messages: list[dict[str, str]]) -> str:
        reply = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format=RESPONSE_FORMAT,
            reasoning_effort="low",  # gpt-oss thinks briefly before answering; low keeps it fast
            include_reasoning=False,  # we only want the answer back
            temperature=0,
            max_completion_tokens=MAX_COMPLETION_TOKENS,
        )
        content = reply.choices[0].message.content
        if not content:
            raise InvalidReply("empty reply")
        return content


def parse_reply(raw: str, transcript: str, red_flag_floor: int = DEFAULT_RED_FLAG_FLOOR) -> TextSignal:
    """Turn the model's JSON into a TextSignal, or raise InvalidReply.

    Strict mode should already give the right shape, but the reply is still
    checked here: a wrong type or range must never reach the risk meter.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidReply(f"not JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise InvalidReply("not a JSON object")
    missing = [key for key in OUTPUT_SCHEMA["required"] if key not in data]
    if missing:
        raise InvalidReply(f"missing {', '.join(missing)}")

    risk = data["risk"]
    # bool is a kind of int in Python, so rule it out by name.
    if isinstance(risk, bool) or not isinstance(risk, int) or not 0 <= risk <= 100:
        raise InvalidReply(f"risk must be a whole number from 0 to 100 (got {risk!r})")
    scam_type = data["scam_type"]
    if scam_type not in ALLOWED_SCAM_TYPES:
        raise InvalidReply(f"unknown scam_type {scam_type!r}")
    evidence = data["evidence"]
    if not isinstance(evidence, list) or not all(isinstance(p, str) for p in evidence):
        raise InvalidReply("evidence must be a list of strings")
    red_flags = data["red_flags"]
    if not isinstance(red_flags, list) or not all(flag in RED_FLAGS for flag in red_flags):
        raise InvalidReply(f"red_flags must be names from the red flag list (got {red_flags!r})")
    reason, next_action = data["reason"], data["next_action"]
    for name, value in (("reason", reason), ("next_action", next_action)):
        if not isinstance(value, str) or not value.strip():
            raise InvalidReply(f"{name} must be a non-empty string")

    red_flags = tuple(dict.fromkeys(red_flags))  # drop repeats, keep order
    if red_flags:
        # A red flag is high risk however politely it was put.
        risk = max(risk, red_flag_floor)
        if scam_type == NO_SCAM:
            scam_type = OTHER_SCAM  # never label a call with a red flag "no scam"

    return TextSignal(
        risk=risk,
        scam_type=scam_type,
        evidence=phrases_from_transcript(evidence, transcript),
        red_flags=red_flags,
        reason=_clip(reason),
        next_action=_clip(next_action),
    )


def phrases_from_transcript(phrases: list[str], transcript: str) -> tuple[str, ...]:
    """Keep only evidence that was really said, so the screen never quotes words nobody spoke.

    Matching ignores case, punctuation and curly quotes, which the model may change.
    """
    spoken = f" {normalised_words(transcript)} "
    kept: list[str] = []
    for phrase in phrases:
        phrase = phrase.strip()
        words = normalised_words(phrase)
        if words and f" {words} " in spoken and phrase not in kept:
            kept.append(phrase)
    return tuple(kept[:MAX_EVIDENCE])


def normalised_words(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    return " ".join(re.findall(r"[a-z0-9']+", text))


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 1].rstrip() + "…"


def _describe(exc: Exception) -> str:
    if isinstance(exc, groq.RateLimitError):
        return "Groq rate limit reached"
    if isinstance(exc, (groq.AuthenticationError, groq.PermissionDeniedError)):
        return "Groq rejected the API key"
    if isinstance(exc, groq.APIStatusError):
        return f"Groq returned HTTP {exc.status_code}"
    if isinstance(exc, groq.APIConnectionError):
        return "could not reach Groq"
    return str(exc) or type(exc).__name__


def _unknown(error: str) -> TextSignal:
    logger.warning("Scam check gave no verdict: %s", error)
    return TextSignal.unknown(error)
