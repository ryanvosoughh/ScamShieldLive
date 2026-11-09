"""What the app says at each risk level: one line for the screen, one to say out loud.

The screen line is the headline on the risk meter, readable at a glance. The
spoken line is what SpeechAlert says. None means say nothing.

Rules every line follows:
- Never call a call "safe". GREEN only means nothing worrying has been heard yet.
- A warning always says what to do, not only that something is wrong.
- Spoken lines are short: the person is still on the call, listening to the caller.
- GREEN is never spoken. Talking over a normal call is an interruption, and
  "this call is fine" is a promise the app can't make.
- UNKNOWN is spoken. Someone relying on the voice would otherwise take silence
  to mean nothing is wrong, when the check has stopped working.

Gran mode is for an older person who may panic or freeze when warned: fewer
words, everyday language ("a trick", "numbers" rather than "scam", "codes"),
one short sentence per idea, and nothing that sounds like a telling-off.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models import Persona, RiskLevel


@dataclass(frozen=True)
class AlertLines:
    screen: str
    spoken: str | None  # None: stay quiet at this level


WORDING: dict[Persona, dict[RiskLevel, AlertLines]] = {
    Persona.STANDARD: {
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
            spoken="The scam check isn't working right now. "
            "Be careful with any request for money or codes.",
        ),
    },
    Persona.GRAN: {
        RiskLevel.GREEN: AlertLines(
            screen="Nothing worrying yet",
            spoken=None,
        ),
        RiskLevel.YELLOW: AlertLines(
            screen="Go carefully",
            spoken="Go carefully. Don't send any money yet.",
        ),
        RiskLevel.RED: AlertLines(
            screen="This might be a trick",
            spoken="This might be a trick. Don't send money or give any numbers. "
            "Hang up and call someone you trust.",
        ),
        RiskLevel.UNKNOWN: AlertLines(
            screen="Can't check right now",
            spoken="I can't check this call right now. Don't send any money.",
        ),
    },
}


def lines_for(level: RiskLevel, persona: Persona = Persona.STANDARD) -> AlertLines:
    """The screen and spoken line for this level, in this persona's wording."""
    return WORDING[persona][level]
