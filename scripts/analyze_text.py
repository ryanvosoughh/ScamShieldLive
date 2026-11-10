"""Run the live scam check by hand on some text, without the server or a call.

    .venv/bin/python scripts/analyze_text.py "Hi Nana, it's me, I need bail money, don't tell Mum"
    pbpaste | .venv/bin/python scripts/analyze_text.py        # text from the clipboard (macOS)

Each run is one Groq call (about 1,000 tokens of the free allowance).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.analysis import ScamAnalyzer  # noqa: E402
from app.config import ConfigError, Settings  # noqa: E402
from app.scoring import RiskScorer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check some call text for scam signs.")
    parser.add_argument("text", nargs="?", help="the call text (read from stdin if left out)")
    args = parser.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()
    if not text.strip():
        print("Give some call text as an argument, or pipe it in.", file=sys.stderr)
        return 1

    try:
        settings = Settings.load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    analyzer = ScamAnalyzer.from_settings(settings)
    if analyzer is None:
        print("GROQ_API_KEY is not set in .env. Get a key at https://console.groq.com/keys", file=sys.stderr)
        return 1

    started = time.monotonic()
    signal = asyncio.run(analyzer.analyze(text))
    took = time.monotonic() - started

    if signal.is_unknown:
        print(f"\n  No verdict ({signal.error}). The app would show this as UNKNOWN, not safe.\n")
        return 1
    # The meter can be redder than the risk: the scorer turns any red flag into red.
    level = RiskScorer.from_settings(settings).update(signal).level
    print(f"\n  Meter:     {level.value.upper()}")
    print(f"  Risk:      {signal.risk}/100   ({signal.scam_type})")
    print(f"  Reason:    {signal.reason}")
    print(f"  Do this:   {signal.next_action}")
    if signal.red_flags:
        print(f"  Red flags: {', '.join(signal.red_flags)}")
    for phrase in signal.evidence:
        print(f'  Evidence:  "{phrase}"')
    print(f"\n  {settings.live_model} answered in {took:.1f} s\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
