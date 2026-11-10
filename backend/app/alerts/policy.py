"""AlertPolicy: after each check, decide what the screen shows and whether to speak.

The screen always follows the current level. Speaking is rarer, because a voice
talking over the call is an interruption. Each warning is said once, as the
call gets worse: yellow, then red. Nothing else is spoken:

- the same warning again: checks run every few seconds, and "this sounds like
  a scam" every 4 s would drown out the call;
- a step down: "be careful" just after "this sounds like a scam" would sound
  like the danger had passed;
- green, or a check that failed (see wording.py).

One AlertPolicy per call: it remembers the loudest warning it has said.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.alerts.wording import lines_for
from app.models import RiskLevel, RiskState

# The warnings, quietest first. Green and unknown are never spoken.
_LOUDNESS = {RiskLevel.YELLOW: 1, RiskLevel.RED: 2}


@dataclass(frozen=True)
class Alert:
    level: RiskLevel
    screen: str  # the headline for the risk meter; always set
    spoken: str | None  # say this now; None means say nothing this time


class AlertPolicy:
    def __init__(self) -> None:
        self._loudest_said = 0  # 0 until a warning has been said

    def decide(self, state: RiskState) -> Alert:
        lines = lines_for(state.level)
        loudness = _LOUDNESS.get(state.level, 0)
        if loudness > self._loudest_said:
            self._loudest_said = loudness
            return Alert(state.level, lines.screen, lines.spoken)
        return Alert(state.level, lines.screen, None)
