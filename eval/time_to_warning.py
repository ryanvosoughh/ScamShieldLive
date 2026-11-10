"""Phase 4D: how soon the meter warns on the three demo calls, with the real scam check.

    .venv/bin/python eval/time_to_warning.py      # about 3 minutes; saves eval/timing.json

Each demo call is played in real time through the same CallSession a browser
call uses: the scripted words arrive as live text would, and the real
ScamAnalyzer (Groq), the scorer and the check pacing all run as normal. The
time each new state reaches the "browser" is recorded.

The demo scripts mark where the warning signs are, so the report can say how
long after each one the meter changed:
  - the warning sign: the first line the script rates yellow or above;
  - the ask: the first line with a red flag, such as "buy gift cards".
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from run_eval import ROOT, git_commit, prompt_fingerprint  # also puts backend/ on the path

from app.analysis import ScamAnalyzer, TranscriptWindow  # noqa: E402
from app.config import ConfigError, Settings  # noqa: E402
from app.demo.scenarios import CALLS_DIR, Scenario, load_scenario  # noqa: E402
from app.scoring import RiskScorer  # noqa: E402
from app.session import CallSession  # noqa: E402
from app.stt import ReplaySTT  # noqa: E402

TIMING_FILE = ROOT / "eval" / "timing.json"
# A call can use up to 5 checks a minute; a pause between calls keeps the three
# of them together under Groq's free-tier limit.
PAUSE_BETWEEN_CALLS_SECONDS = 30.0


def markers(scenario: Scenario, yellow_threshold: int) -> dict:
    """When the script's warning sign and its ask end, in seconds from the start of the call."""
    sign = next((line.end for line in scenario.lines if line.verdict and line.verdict.risk >= yellow_threshold), None)
    ask = next((line.end for line in scenario.lines if line.verdict and line.verdict.red_flags), None)
    return {"warning_sign_at": sign, "ask_at": ask}


async def time_call(scenario: Scenario, analyzer, settings: Settings) -> dict:
    """Play one demo call through a real CallSession and note when each state arrives."""
    states: list[dict] = []

    async def send(message: dict) -> None:
        if message["type"] == "state":
            failed = message["breakdown"][0].startswith("Words: no result")
            states.append({"at": round(time.monotonic() - started, 1), "level": message["level"], "failed": failed})

    stt = ReplaySTT(scenario)
    session = CallSession(
        stt=stt,
        send=send,
        analyzer=analyzer,
        scorer=RiskScorer.from_settings(settings),
        window=TranscriptWindow(window_seconds=settings.window_seconds),
        check_interval=settings.analysis_interval_seconds,
        checks_per_minute=settings.checks_per_minute,
    )
    started = time.monotonic()
    await session.start()
    await stt.finished.wait()
    await session.end()

    def first(*levels: str) -> float | None:
        return next((state["at"] for state in states if state["level"] in levels), None)

    return {
        "id": scenario.id,
        "title": scenario.title,
        "kind": scenario.kind,
        "seconds": scenario.duration,
        **markers(scenario, settings.risk_yellow_threshold),
        "first_warning_at": first("yellow", "red"),
        "first_red_at": first("red"),
        "checks": len(states),
        "failed_checks": sum(state["failed"] for state in states),
        "states": states,
    }


async def run(analyzer, settings: Settings) -> list[dict]:
    calls = []
    for number, path in enumerate(sorted(CALLS_DIR.glob("*.json")), 1):
        if number > 1:
            await asyncio.sleep(PAUSE_BETWEEN_CALLS_SECONDS)
        scenario = load_scenario(path.stem)
        print(f"  Playing {scenario.title} ({scenario.duration:.0f} s)...")
        call = await time_call(scenario, analyzer, settings)
        calls.append(call)
        print(
            f"    first warning {call['first_warning_at']} s, first red {call['first_red_at']} s,"
            f" {call['checks']} checks ({call['failed_checks']} failed)"
        )
    return calls


def main() -> int:
    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    analyzer = ScamAnalyzer.from_settings(settings)
    if analyzer is None:
        print("GROQ_API_KEY is not set in .env. Get a key at https://console.groq.com/keys", file=sys.stderr)
        return 1

    print(f"\n  Timing the demo calls with {settings.live_model}, in real time\n")
    calls = asyncio.run(run(analyzer, settings))
    info = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.live_model,
        "yellow_threshold": settings.risk_yellow_threshold,
        "red_threshold": settings.risk_red_threshold,
        "check_interval_seconds": settings.analysis_interval_seconds,
        "checks_per_minute": settings.checks_per_minute,
        "prompt_sha256": prompt_fingerprint(),
        "git_commit": git_commit(),
    }
    TIMING_FILE.write_text(json.dumps({"run": info, "calls": calls}, indent=2) + "\n")
    print(f"\n  Saved {TIMING_FILE.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
