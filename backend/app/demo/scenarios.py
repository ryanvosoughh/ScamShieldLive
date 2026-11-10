"""Scripted demo calls: what is said, when, and (for keyless demos) the verdict after each line.

Each call is a JSON file in calls/. Every line has start and end times in
seconds from the start of the call. A line may carry a "verdict": what the
scam check concludes once that line has been heard. The verdicts are only used
when there is no Groq key; with a key, the real check runs on the scripted words.

Scripts are checked when they load, so a typo can't reach the screen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.analysis.analyzer import ALLOWED_SCAM_TYPES, phrases_from_transcript
from app.analysis.prompts import RED_FLAGS

CALLS_DIR = Path(__file__).resolve().parent / "calls"
DEFAULT_SCENARIO = "grandchild_scam"


class DemoError(Exception):
    """A demo call can't be played. The message is safe to show to the user."""


@dataclass(frozen=True)
class Verdict:
    risk: int
    scam_type: str
    red_flags: tuple[str, ...]
    evidence: tuple[str, ...]
    reason: str
    next_action: str


@dataclass(frozen=True)
class Line:
    start: float  # seconds from the start of the call
    end: float
    text: str
    verdict: Verdict | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    kind: str  # "scam" or "normal"
    description: str
    lines: tuple[Line, ...]
    tail_seconds: float  # quiet time after the last line before the call ends

    @property
    def duration(self) -> float:
        return self.lines[-1].end + self.tail_seconds


def list_scenarios() -> list[str]:
    """The ids of every demo call, from the files in calls/."""
    return sorted(path.stem for path in CALLS_DIR.glob("*.json"))


@cache
def load_scenario(scenario_id: str) -> Scenario:
    """Load and check one demo call. Only ids from list_scenarios() are accepted,
    so a name sent by the browser can never point at another file."""
    known = list_scenarios()
    if scenario_id not in known:
        raise DemoError(f"There is no demo call called {scenario_id[:40]!r}. Choose one of: {', '.join(known)}.")
    path = CALLS_DIR / f"{scenario_id}.json"
    try:
        data = json.loads(path.read_text())
        scenario = _build(scenario_id, data)
    except (KeyError, TypeError, ValueError) as exc:
        raise DemoError(f"The demo call {scenario_id!r} is broken: {exc}") from None
    return scenario


def _build(scenario_id: str, data: dict) -> Scenario:
    lines = tuple(
        Line(
            start=float(raw["start"]),
            end=float(raw["end"]),
            text=str(raw["text"]).strip(),
            verdict=_verdict(raw["verdict"]) if "verdict" in raw else None,
        )
        for raw in data["lines"]
    )
    if not lines:
        raise ValueError("it has no lines")
    previous_end = 0.0
    for number, line in enumerate(lines, 1):
        if not line.text:
            raise ValueError(f"line {number} is empty")
        if line.end <= line.start or line.start < previous_end:
            raise ValueError(f"line {number} has bad times ({line.start} to {line.end})")
        previous_end = line.end

    script = " ".join(line.text for line in lines)
    for number, line in enumerate(lines, 1):
        if line.verdict and len(phrases_from_transcript(list(line.verdict.evidence), script)) != len(line.verdict.evidence):
            raise ValueError(f"line {number} has evidence that is never said")

    kind = data["kind"]
    if kind not in ("scam", "normal"):
        raise ValueError(f"kind must be 'scam' or 'normal' (got {kind!r})")
    return Scenario(
        id=scenario_id,
        title=data["title"],
        kind=kind,
        description=data["description"],
        lines=lines,
        tail_seconds=float(data.get("tail_seconds", 5)),
    )


def _verdict(raw: dict) -> Verdict:
    verdict = Verdict(
        risk=int(raw["risk"]),
        scam_type=raw["scam_type"],
        red_flags=tuple(raw["red_flags"]),
        evidence=tuple(raw["evidence"]),
        reason=raw["reason"],
        next_action=raw["next_action"],
    )
    if not 0 <= verdict.risk <= 100:
        raise ValueError(f"risk {verdict.risk} is not 0-100")
    if verdict.scam_type not in ALLOWED_SCAM_TYPES:
        raise ValueError(f"unknown scam_type {verdict.scam_type!r}")
    unknown = [flag for flag in verdict.red_flags if flag not in RED_FLAGS]
    if unknown:
        raise ValueError(f"unknown red flags {unknown}")
    if not verdict.reason or not verdict.next_action:
        raise ValueError("a verdict needs a reason and a next action")
    return verdict
