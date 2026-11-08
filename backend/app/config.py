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
    summary_model: str
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
        reader = _EnvReader(env)
        settings = cls(
            demo_mode=reader.boolean("DEMO_MODE", False),
            deepgram_api_key=reader.text("DEEPGRAM_API_KEY", ""),
            groq_api_key=reader.text("GROQ_API_KEY", ""),
            deepgram_model=reader.text("DEEPGRAM_MODEL", "nova-3"),
            live_model=reader.text("LIVE_MODEL", "openai/gpt-oss-120b"),
            summary_model=reader.text("SUMMARY_MODEL", "openai/gpt-oss-120b"),
            risk_yellow_threshold=reader.integer("RISK_YELLOW_THRESHOLD", 40),
            risk_red_threshold=reader.integer("RISK_RED_THRESHOLD", 70),
            analysis_interval_seconds=reader.number("ANALYSIS_INTERVAL_SECONDS", 4.0),
            checks_per_minute=reader.integer("CHECKS_PER_MINUTE", 5),
            window_seconds=reader.number("WINDOW_SECONDS", 30.0),
            host=reader.text("HOST", "127.0.0.1"),
            port=reader.integer("PORT", 8000),
        )
        reader.raise_if_errors()
        return settings

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
        if self.analysis_interval_seconds <= 0:
            errors.append("ANALYSIS_INTERVAL_SECONDS must be greater than 0.")
        if self.checks_per_minute < 1:
            errors.append("CHECKS_PER_MINUTE must be at least 1.")
        if self.window_seconds < self.analysis_interval_seconds:
            errors.append("WINDOW_SECONDS must be at least ANALYSIS_INTERVAL_SECONDS.")
        if not 1 <= self.port <= 65535:
            errors.append(f"PORT must be between 1 and 65535 (got {self.port}).")

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


class _EnvReader:
    """Parses typed values and collects every bad value, so the user sees all problems at once."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env
        self._errors: list[str] = []

    def _raw(self, name: str) -> str | None:
        value = self._env.get(name)
        if value is None or value.strip() == "":
            return None
        return value.strip()

    def text(self, name: str, default: str) -> str:
        return self._raw(name) or default

    def boolean(self, name: str, default: bool) -> bool:
        raw = self._raw(name)
        if raw is None:
            return default
        if raw.lower() in {"1", "true", "yes", "on"}:
            return True
        if raw.lower() in {"0", "false", "no", "off"}:
            return False
        self._errors.append(f"{name} must be true or false (got {raw!r}).")
        return default

    def integer(self, name: str, default: int) -> int:
        raw = self._raw(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            self._errors.append(f"{name} must be a whole number (got {raw!r}).")
            return default

    def number(self, name: str, default: float) -> float:
        raw = self._raw(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            self._errors.append(f"{name} must be a number (got {raw!r}).")
            return default

    def raise_if_errors(self) -> None:
        if self._errors:
            raise ConfigError("\n  - ".join(["Configuration problem:", *self._errors]))
