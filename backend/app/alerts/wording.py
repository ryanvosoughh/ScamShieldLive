"""What the app says at each risk level: one line for the screen, one to say out loud.

The screen line is the headline on the risk meter, readable at a glance. The
spoken line is what SpeechAlert says. None means say nothing.

Rules every line follows:
- Never call a call "safe". GREEN only means nothing worrying has been heard yet.
- A warning always says what to do, not only that something is wrong.
- Spoken lines are short: the person is still on the call, listening to the caller.
- Only warnings (YELLOW and RED) are spoken. Talking over a normal call is an
  interruption, and "this call is fine" is a promise the app can't make. A
  check that failed (UNKNOWN) shows on the meter but isn't worth interrupting
  the call for: one rate-limit blip would otherwise be said out loud.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models import RiskLevel


@dataclass(frozen=True)
class AlertLines:
    screen: str
    spoken: str | None  # None: stay quiet at this level


WORDING: dict[RiskLevel, AlertLines] = {
    RiskLevel.GREEN: AlertLines(
        screen="No warning signs so far",
        spoken=None,
    ),
    RiskLevel.YELLOW: AlertLines(
        screen="Be careful",
        spoken="Be careful. This call has some warning signs. "
        "Don't agree to send money or share any details yet.",
    ),
    RiskLevel.RED: AlertLines(
        screen="This sounds like a scam",
        spoken="Warning. This sounds like a scam. Don't send money or share any codes. "
        "Hang up and call back on a number you already know.",
    ),
    RiskLevel.UNKNOWN: AlertLines(
        screen="Couldn't check the call",
        spoken=None,
    ),
}


def lines_for(level: RiskLevel) -> AlertLines:
    """The screen and spoken line for this level."""
    return WORDING[level]
