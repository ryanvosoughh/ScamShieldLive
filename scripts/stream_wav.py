"""Stream a WAV file through /ws/call, the way the browser does, and print the transcript.

Checks the server and Deepgram without a microphone, and measures the delay
from speech to text the same way the page does: seconds of audio sent so far,
minus the end time of the text that came back.

    .venv/bin/python run.py                                   # in one terminal
    .venv/bin/python scripts/stream_wav.py samples/grandchild_scam.wav

The WAV must be 16 kHz, mono, 16-bit (what scripts/make_sample_audio.sh makes).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import wave
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1600  # 100 ms, the same size the browser sends
CHUNK_BYTES = CHUNK_SAMPLES * 2


class CheckFailed(Exception):
    """A problem the user can fix. The message is printed as is."""


def read_pcm(path: Path) -> bytes:
    try:
        with wave.open(str(path), "rb") as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except FileNotFoundError:
        raise CheckFailed(f"{path} does not exist. Make the sample clips with: bash scripts/make_sample_audio.sh")
    except (wave.Error, EOFError) as exc:
        raise CheckFailed(f"{path} is not a readable WAV file ({exc}).")

    if (channels, width, rate) != (1, 2, SAMPLE_RATE):
        raise CheckFailed(
            f"{path} is {rate} Hz, {channels} channel(s), {width * 8}-bit. It needs to be 16000 Hz, mono, 16-bit.\n"
            f"  Convert it on macOS:  afconvert -f WAVE -d LEI16@16000 -c 1 {path} out.wav\n"
            f"  or with ffmpeg:       ffmpeg -i {path} -ar 16000 -ac 1 -sample_fmt s16 out.wav"
        )
    if not frames:
        raise CheckFailed(f"{path} has no audio in it.")
    return frames


class Run:
    """What happened during one streamed call."""

    def __init__(self) -> None:
        self.sent_samples = 0
        self.final_lags: list[float] = []
        self.interim_lags: list[float] = []
        self.final_lines: list[str] = []
        self.error: str | None = None

    def lag(self, text_end: float) -> float | None:
        lag = self.sent_samples / SAMPLE_RATE - text_end
        return lag if lag >= 0 else None


async def stream(url: str, pcm: bytes) -> Run:
    run = Run()
    try:
        socket = await connect(url, open_timeout=10)
    except (OSError, asyncio.TimeoutError, InvalidHandshake, InvalidURI) as exc:
        raise CheckFailed(
            f"Could not connect to {url} ({exc.__class__.__name__}).\n"
            "  Is the server running? Start it in another terminal with: .venv/bin/python run.py"
        )

    async with socket:
        first = json.loads(await socket.recv())
        if first.get("type") != "ready":
            raise CheckFailed(f"The server did not get ready: {first.get('message', first)}")

        sender = asyncio.create_task(_send_in_real_time(socket, pcm, run))
        try:
            await _receive(socket, run)
        except ConnectionClosed:
            if run.error is None:
                run.error = "The server closed the connection before the call ended."
        finally:
            sender.cancel()
    return run


async def _send_in_real_time(socket, pcm: bytes, run: Run) -> None:
    """Send 100 ms chunks on a wall-clock schedule, so Deepgram hears the clip at normal speed."""
    started = time.monotonic()
    for offset in range(0, len(pcm), CHUNK_BYTES):
        chunk = pcm[offset : offset + CHUNK_BYTES]
        due = started + offset / 2 / SAMPLE_RATE
        await asyncio.sleep(max(0.0, due - time.monotonic()))
        await socket.send(chunk)
        run.sent_samples += len(chunk) // 2
    await socket.send(json.dumps({"type": "stop"}))


async def _receive(socket, run: Run) -> None:
    async for raw in socket:
        message = json.loads(raw)
        kind = message.get("type")
        if kind == "ended":
            return
        if kind == "error":
            run.error = message.get("message", "unknown error")
            continue
        if kind != "transcript" or not message.get("text"):
            continue

        lag = run.lag(message["end"])
        if not message["is_final"]:
            if lag is not None:
                run.interim_lags.append(lag)
            continue

        if lag is not None:
            run.final_lags.append(lag)
        run.final_lines.append(message["text"])
        shown = f"{lag:.1f} s" if lag is not None else "n/a"
        print(f"  [{message['start']:5.1f}s] {message['text']}   (delay {shown})")


def _describe(lags: list[float]) -> str:
    if not lags:
        return "none received"
    return f"median {statistics.median(lags):.1f} s, worst {max(lags):.1f} s ({len(lags)} updates)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream a WAV through ScamShield Live and print the transcript.")
    parser.add_argument("wav", type=Path, help="16 kHz mono 16-bit WAV file")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/call", help="call socket (default: %(default)s)")
    args = parser.parse_args()

    try:
        pcm = read_pcm(args.wav)
        seconds = len(pcm) / 2 / SAMPLE_RATE
        print(f"\nStreaming {args.wav} ({seconds:.1f} s) to {args.url} in real time...\n")
        run = asyncio.run(stream(args.url, pcm))
    except CheckFailed as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

    print()
    print(f"  Interim text delay: {_describe(run.interim_lags)}")
    print(f"  Final text delay:   {_describe(run.final_lags)}")
    if run.error:
        print(f"\n  Error from the server: {run.error}\n", file=sys.stderr)
        return 1
    if not run.final_lines:
        print("\n  No text came back. Is there speech in the clip?\n", file=sys.stderr)
        return 1
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
