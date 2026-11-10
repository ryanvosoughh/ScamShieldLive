"""Phase 4B: run every case in eval/cases.json through the live scam check and save what happened.

    .venv/bin/python eval/run_eval.py             # all cases, about 5 minutes; saves eval/results.json
    .venv/bin/python eval/run_eval.py --limit 3   # a quick try on the first 3 cases; saves nothing

Each case is checked the way a live call is: one ScamAnalyzer call with the
live prompt (about 1,350 tokens of Groq's free allowance), then RiskScorer,
which gives the level the risk meter would show. A failed check (a rate limit,
a timeout) is tried again after a pause. If it keeps failing, the case is
saved as unknown, and never counted as a miss or a false alarm.

The results file also records the model, the thresholds, and short
fingerprints of the prompt, the cases and the code, so a result can always be
traced back to what produced it.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analysis import ScamAnalyzer  # noqa: E402
from app.analysis.prompts import OUTPUT_SCHEMA, SYSTEM_PROMPT  # noqa: E402
from app.config import ConfigError, Settings  # noqa: E402
from app.models import RiskLevel  # noqa: E402
from app.scoring import RiskScorer  # noqa: E402

CASES_FILE = ROOT / "eval" / "cases.json"
RESULTS_FILE = ROOT / "eval" / "results.json"
# Groq's free tier allows about 8,000 tokens a minute and a check is about
# 1,350, so one check every 12 s stays under it.
PAUSE_SECONDS = 12.0
RETRY_PAUSE_SECONDS = 30.0  # after a failed check: long enough for a rate limit to clear
ATTEMPTS = 3


def outcome(label: str, level: RiskLevel) -> str:
    """What the meter's level means for a case with this label."""
    if level is RiskLevel.UNKNOWN:
        return "unknown"
    warned = level in (RiskLevel.YELLOW, RiskLevel.RED)
    if label == "scam":
        return "caught" if warned else "missed"
    return "false_alarm" if warned else "correct"


async def check_case(case: dict, analyzer, settings: Settings, retry_pause: float = RETRY_PAUSE_SECONDS) -> dict:
    """One case through the analyser and a fresh scorer, trying again if the check fails."""
    for attempt in range(1, ATTEMPTS + 1):
        started = time.monotonic()
        signal = await analyzer.analyze(case["text"])
        seconds = time.monotonic() - started
        if not signal.is_unknown or attempt == ATTEMPTS:
            break
        print(f"      no verdict ({signal.error}); trying again in {retry_pause:g} s")
        await asyncio.sleep(retry_pause)
    level = RiskScorer.from_settings(settings).update(signal).level
    return {
        "id": case["id"],
        "label": case["label"],
        "expected_scam_type": case["scam_type"],
        "tags": case["tags"],
        "level": level.value,
        "outcome": outcome(case["label"], level),
        "risk": signal.risk,
        "scam_type": signal.scam_type,
        "red_flags": list(signal.red_flags),
        "evidence": list(signal.evidence),
        "reason": signal.reason,
        "seconds": round(seconds, 2),
        "attempts": attempt,
        "error": signal.error,
    }


async def run(cases: list[dict], analyzer, settings: Settings, pause: float = PAUSE_SECONDS) -> list[dict]:
    results = []
    for number, case in enumerate(cases, 1):
        if number > 1:
            await asyncio.sleep(pause)
        result = await check_case(case, analyzer, settings)
        results.append(result)
        risk = "  -" if result["risk"] is None else f"{result['risk']:>3}"
        flags = ", ".join(result["red_flags"]) or "no red flags"
        print(
            f"  [{number:>2}/{len(cases)}] {case['id']:<34} {case['label']:<6} -> {result['level'].upper():<7}"
            f" risk {risk}  {result['outcome']:<11} {result['seconds']:4.1f} s  ({flags})"
        )
    return results


def print_summary(results: list[dict]) -> None:
    count = Counter(result["outcome"] for result in results)
    scams = sum(result["label"] == "scam" for result in results)
    normals = len(results) - scams
    print(f"\n  Scams caught:  {count['caught']} of {scams} (missed {count['missed']})")
    print(f"  Normal calls:  {count['correct']} of {normals} left green (false alarms {count['false_alarm']})")
    if count["unknown"]:
        print(f"  No verdict:    {count['unknown']}, not counted either way")
    times = [result["seconds"] for result in results if result["outcome"] != "unknown"]
    if times:
        print(f"  Check time:    average {statistics.mean(times):.1f} s, worst {max(times):.1f} s\n")


def run_info(settings: Settings, cases_text: str, cases: int) -> dict:
    """What produced these results, so they can be traced back later."""
    prompt = SYSTEM_PROMPT + json.dumps(OUTPUT_SCHEMA, sort_keys=True)
    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.live_model,
        "yellow_threshold": settings.risk_yellow_threshold,
        "red_threshold": settings.risk_red_threshold,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()[:12],
        "cases_sha256": hashlib.sha256(cases_text.encode()).hexdigest()[:12],
        "git_commit": _git_commit(),
        "cases": cases,
    }


def _git_commit() -> str | None:
    """The commit the code came from, marked if the code or cases had uncommitted changes."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        changed = subprocess.run(
            ["git", "status", "--porcelain", "--", "backend", "eval/cases.json"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{commit} with uncommitted changes" if changed else commit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the test set through the live scam check.")
    parser.add_argument("--limit", type=int, help="check only the first N cases, and save nothing")
    args = parser.parse_args()

    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    analyzer = ScamAnalyzer.from_settings(settings)
    if analyzer is None:
        print("GROQ_API_KEY is not set in .env. Get a key at https://console.groq.com/keys", file=sys.stderr)
        return 1

    cases_text = CASES_FILE.read_text()
    cases = json.loads(cases_text)
    if args.limit:
        cases = cases[: args.limit]
    print(f"\n  Checking {len(cases)} cases with {settings.live_model}, one every {PAUSE_SECONDS:g} s\n")
    results = asyncio.run(run(cases, analyzer, settings))
    print_summary(results)

    if args.limit:
        print("  A trial run, so nothing was saved.\n")
        return 0
    report = {"run": run_info(settings, cases_text, len(cases)), "results": results}
    RESULTS_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"  Saved {RESULTS_FILE.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
