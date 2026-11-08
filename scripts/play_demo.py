"""Play a scripted demo call through the server and print what the app would show.

    .venv/bin/python run.py                                      # in one terminal
    .venv/bin/python scripts/play_demo.py                        # the grandchild scam
    .venv/bin/python scripts/play_demo.py bank_scam              # or bank_scam, normal_call

Needs no keys. Without GROQ_API_KEY the verdicts come from the script; with it,
the real scam check runs on the scripted words.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI


async def play(url: str) -> int:
    try:
        socket = await connect(url, open_timeout=10)
    except (OSError, asyncio.TimeoutError, InvalidHandshake, InvalidURI) as exc:
        print(
            f"\nCould not connect to {url} ({exc.__class__.__name__}).\n"
            "  Is the server running? Start it in another terminal with: .venv/bin/python run.py\n",
            file=sys.stderr,
        )
        return 1

    last_level = None
    async with socket:
        try:
            async for raw in socket:
                message = json.loads(raw)
                kind = message["type"]
                if kind == "ready":
                    demo = message.get("demo") or {}
                    source = "scripted verdicts" if demo.get("scripted_analysis") else "live Groq check"
                    print(f"\n  Demo call: {demo.get('title', '?')} ({source})\n")
                elif kind == "transcript" and message["is_final"] and message["text"]:
                    print(f"  [{message['start']:5.1f}s] {message['text']}")
                elif kind == "state":
                    last_level = message["level"]
                    score = "n/a" if message["score"] is None else f"{message['score']:.0f}"
                    print(f"     >> {last_level.upper()} ({score}): {message['reason']}")
                    if last_level in ("yellow", "red"):
                        print(f"        Do this: {message['next_action']}")
                elif kind == "error":
                    print(f"\n  Error: {message['message']}\n", file=sys.stderr)
                    return 1
                elif kind == "ended":
                    break
        except ConnectionClosed:
            print("\n  The server closed the connection.\n", file=sys.stderr)
            return 1

    print(f"\n  Call over. Final level: {last_level.upper() if last_level else 'none'}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Play a scripted demo call through ScamShield Live.")
    parser.add_argument("scenario", nargs="?", default="grandchild_scam", help="grandchild_scam, bank_scam or normal_call")
    parser.add_argument("--server", default="ws://127.0.0.1:8000", help="server address (default: %(default)s)")
    args = parser.parse_args()
    try:
        return asyncio.run(play(f"{args.server}/ws/call?scenario={args.scenario}"))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
