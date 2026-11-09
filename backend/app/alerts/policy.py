"""AlertPolicy: after each check, decide what the screen shows and whether to speak.

The screen always follows the current level. Speaking is rarer, because a voice
talking over the call is an interruption:

- A level is spoken when it is higher than the last thing said: going from
  green to yellow, or yellow to red, speaks straight away.
- The same alert is not repeated until the cooldown has passed. Checks run
  every few seconds, and "this sounds like a scam" every 4 s would drown out
  the call. Once the cooldown is over it is said again as a reminder, but only
  if the call is still going: a check only runs after new speech.
- A step down is never spoken. Saying "be careful" just after "this sounds like
  a scam" would sound like the danger had passed.
- Quiet mode never speaks, for when the caller might hear the warning. The
  screen still shows everything.

One AlertPolicy per call: it remembers what it last said.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.alerts.wording import lines_for
from app.models import Persona, RiskLevel, RiskState

# How loud each level is when spoken. UNKNOWN sits above GREEN: "the check has
# stopped working" is worth saying, but it is not a warning about the caller.
LOUDNESS = {RiskLevel.GREEN: 0, RiskLevel.UNKNOWN: 1, RiskLevel.YELLOW: 2, RiskLevel.RED: 3}

DEFAULT_COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True)
class Alert:
    level: RiskLevel
    screen: str  # the headline for the risk meter; always set
    spoken: str | None  # say this now; None means say nothing this time


class AlertPolicy:
    def __init__(self, cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS):
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds can't be negative")
        self.cooldown = cooldown_seconds
        self._last_spoken: RiskLevel | None = None
        self._last_spoken_at = 0.0

    def decide(
        self,
        state: RiskState,
        persona: Persona = Persona.STANDARD,
        quiet_mode: bool = False,
        now: float | None = None,
    ) -> Alert:
        now = time.monotonic() if now is None else now
        lines = lines_for(state.level, persona)
        speak = lines.spoken is not None and not quiet_mode and self._worth_saying(state.level, now)
        if speak:
            self._last_spoken = state.level
            self._last_spoken_at = now
        return Alert(state.level, lines.screen, lines.spoken if speak else None)

    def _worth_saying(self, level: RiskLevel, now: float) -> bool:
        if self._last_spoken is None:
            return True
        if LOUDNESS[level] > LOUDNESS[self._last_spoken]:
            return True  # it got worse: say so at once
        if level == self._last_spoken:
            return now - self._last_spoken_at >= self.cooldown  # a reminder, not a repeat
        return False  # a step down: stay quiet
