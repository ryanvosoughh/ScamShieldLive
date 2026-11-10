"""Settings: keys, model names, thresholds and DEMO_MODE, read from the environment.

Real environment variables win over values in .env, so a reviewer can override
anything on the command line without editing files.
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Settings are missing or invalid. The message is shown to the user as is."""


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    # repr=False keeps keys out of logs and tracebacks.
    deepgram_api_key: str = field(repr=False)
    groq_api_key: str = field(repr=False)
    deepgram_model: str
    live_model: str
    risk_yellow_threshold: int
    risk_red_threshold: int
    analysis_interval_seconds: float
    checks_per_minute: int
    window_seconds: float
    host: str
    port: int

    @classmethod
    def load(cls, env_file: Path | None = ENV_FILE) -> Settings:
        """Read .env (if present) into the environment, then build Settings from it."""
        if env_file is not None and env_file.exists():
            load_dotenv(env_file, override=False)
        return cls.from_env(os.environ)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Build Settings from a plain mapping. Kept separate from load() so tests need no files."""
        return cls(
            demo_mode=_flag(env, "DEMO_MODE", False),
            deepgram_api_key=_text(env, "DEEPGRAM_API_KEY", ""),
            groq_api_key=_text(env, "GROQ_API_KEY", ""),
            deepgram_model=_text(env, "DEEPGRAM_MODEL", "nova-3"),
            live_model=_text(env, "LIVE_MODEL", "openai/gpt-oss-120b"),
            risk_yellow_threshold=_number(env, "RISK_YELLOW_THRESHOLD", 40, int),
            risk_red_threshold=_number(env, "RISK_RED_THRESHOLD", 70, int),
            analysis_interval_seconds=_number(env, "ANALYSIS_INTERVAL_SECONDS", 4.0, float),
            checks_per_minute=_number(env, "CHECKS_PER_MINUTE", 5, int),
            window_seconds=_number(env, "WINDOW_SECONDS", 30.0, float),
            host=_text(env, "HOST", "127.0.0.1"),
            port=_number(env, "PORT", 8000, int),
        )

    def validate(self) -> list[str]:
        """Fail fast on anything that would break the app. Returns non-fatal warnings."""
        errors: list[str] = []
        warnings: list[str] = []

        if not self.demo_mode and not self.deepgram_api_key:
            errors.append(
                "DEEPGRAM_API_KEY is not set. Live transcription needs it.\n"
                "    Copy .env.example to .env and add your key (console.deepgram.com),\n"
                "    or set DEMO_MODE=true to run without keys."
            )
        if not self.groq_api_key and not self.demo_mode:
            warnings.append(
                "GROQ_API_KEY is not set. Live calls won't be checked for scams; demo calls use scripted verdicts."
            )
        if not 0 <= self.risk_yellow_threshold < self.risk_red_threshold <= 100:
            errors.append(
                "Risk thresholds must satisfy 0 <= RISK_YELLOW_THRESHOLD < RISK_RED_THRESHOLD <= 100 "
                f"(got {self.risk_yellow_threshold} and {self.risk_red_threshold})."
            )

        if errors:
            raise ConfigError("\n  - ".join(["Configuration problem:", *errors]))
        return warnings


def load_or_exit() -> Settings:
    """Load and validate settings; on failure print a friendly message and exit (no traceback)."""
    try:
        settings = Settings.load()
        warnings = settings.validate()
    except ConfigError as exc:
        sys.stderr.write(f"\nScamShield Live could not start.\n  {exc}\n\n")
        raise SystemExit(1) from None
    for warning in warnings:
        logger.warning(warning)
    return settings


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    """The setting with spaces trimmed, or the default when it is missing or blank."""
    return (env.get(name) or "").strip() or default


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _text(env, name, "").lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Configuration problem: {name} must be true or false (got {raw!r}).")


def _number(env: Mapping[str, str], name: str, default, kind):
    raw = _text(env, name, "")
    if not raw:
        return default
    try:
        return kind(raw)
    except ValueError:
        what = "a whole number" if kind is int else "a number"
        raise ConfigError(f"Configuration problem: {name} must be {what} (got {raw!r}).") from None
