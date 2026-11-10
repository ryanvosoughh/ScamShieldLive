"""RiskScorer: turns each scam check of the words into the level the risk meter shows.

Only the words are scored. Tone of voice and a synthetic-voice check were
planned as weak extra signals and are left for later.

The rules, in the order they are applied:

1. Smooth with a moving average so one odd reply doesn't make the meter jump.
   It rises quickly and falls slowly: warnings come fast, calm comes slowly.
2. A red flag in the words goes straight to red, without waiting for the average.
3. Hysteresis: a level is only left once the score is clearly below its
   threshold, so the meter doesn't flicker when the score hovers near a line.
4. Once a call has been red it never shows green again; it can ease to yellow.
5. A failed check never shows as safe. A warning already on screen stays; with
   no warning yet, the meter shows UNKNOWN.
"""
from __future__ import annotations

from app.config import Settings
from app.models import RiskLevel, RiskState, TextSignal

# Moving average (rule 1): how much a new score counts against the running one.
RISE = 0.7  # when the new score is higher
FALL = 0.3  # when it is lower
HYSTERESIS_POINTS = 5.0  # rule 3: how far below a threshold the score must fall
MAX_EVIDENCE = 10  # evidence phrases kept for the whole call

_RANK = {RiskLevel.GREEN: 0, RiskLevel.YELLOW: 1, RiskLevel.RED: 2}


class RiskScorer:
    """One per call: it remembers the call so far."""

    def __init__(
        self,
        yellow_threshold: int = 40,
        red_threshold: int = 70,
        rise: float = RISE,
        fall: float = FALL,
        hysteresis: float = HYSTERESIS_POINTS,
    ) -> None:
        if not 0 <= yellow_threshold < red_threshold <= 100:
            raise ValueError("thresholds must satisfy 0 <= yellow < red <= 100")
        if not 0 < fall <= rise <= 1:
            raise ValueError("smoothing must satisfy 0 < fall <= rise <= 1")
        self.yellow = yellow_threshold
        self.red = red_threshold
        self.rise = rise
        self.fall = fall
        self.hysteresis = hysteresis

        self._score: float | None = None  # the running average
        self._level = RiskLevel.UNKNOWN
        self._been_red = False
        self._latest: TextSignal | None = None  # newest check, even a failed one
        self._last_text: TextSignal | None = None  # newest check that worked
        self._strongest_text: TextSignal | None = None  # highest-risk check so far
        self._evidence: list[str] = []
        self._red_flags: list[str] = []
        self.state = RiskState(level=RiskLevel.UNKNOWN, score=None, breakdown=tuple(self.explain()))

    @classmethod
    def from_settings(cls, settings: Settings) -> RiskScorer:
        return cls(settings.risk_yellow_threshold, settings.risk_red_threshold)

    def update(self, text: TextSignal) -> RiskState:
        """Take the latest check of the words and return the new state."""
        self._latest = text
        if text.is_unknown:
            return self._no_verdict()

        self._remember(text)
        if self._score is None:
            self._score = float(text.risk)
        else:
            weight = self.rise if text.risk > self._score else self.fall
            self._score = weight * text.risk + (1 - weight) * self._score
        if text.red_flags:
            self._score = max(self._score, float(self.red))  # rule 2

        self._level = self._next_level(self._score)
        if self._level is RiskLevel.RED:
            self._been_red = True
        elif self._been_red and self._level is RiskLevel.GREEN:
            self._level = RiskLevel.YELLOW  # rule 4

        self.state = self._build_state(stale=False)
        return self.state

    def explain(self) -> list[str]:
        """What the latest check said about the words, then the smoothed score and level."""
        text = self._latest
        if text is None:
            lines = ["Words: not checked yet"]
        elif text.is_unknown:
            lines = [f"Words: no result ({text.error})" if text.error else "Words: no result"]
        else:
            line = f"Words: {text.risk}/100, {text.scam_type}"
            if text.red_flags:
                line += f", red flags: {', '.join(text.red_flags)}"
            lines = [line]
        if self._score is not None:
            lines.append(f"Smoothed score: {self._score:.0f}/100, level {self._level.value}")
        return lines

    def _next_level(self, score: float) -> RiskLevel:
        """Thresholds with hysteresis (rule 3): go up at once, come down only when clearly below."""
        target = (
            RiskLevel.RED if score >= self.red else RiskLevel.YELLOW if score >= self.yellow else RiskLevel.GREEN
        )
        current = self._level
        if current is RiskLevel.UNKNOWN or _RANK[target] >= _RANK[current]:
            return target
        if current is RiskLevel.RED and score >= self.red - self.hysteresis:
            return RiskLevel.RED
        if score >= self.yellow - self.hysteresis:
            return RiskLevel.YELLOW
        return RiskLevel.GREEN

    def _no_verdict(self) -> RiskState:
        """Rule 5: the words couldn't be checked this time."""
        if self._level in (RiskLevel.YELLOW, RiskLevel.RED):
            # Keep the warning on screen, marked as not up to date.
            self.state = self._build_state(stale=True)
        else:
            # Nothing has warned yet, but we can't say it is still safe.
            self._level = RiskLevel.UNKNOWN
            self.state = RiskState(
                level=RiskLevel.UNKNOWN,
                score=None,
                evidence=tuple(self._evidence),
                red_flags=tuple(self._red_flags),
                stale=self._last_text is not None,
                breakdown=tuple(self.explain()),
            )
        return self.state

    def _remember(self, text: TextSignal) -> None:
        self._last_text = text
        if self._strongest_text is None or text.risk >= self._strongest_text.risk:
            self._strongest_text = text
        for phrase in text.evidence:
            if phrase not in self._evidence and len(self._evidence) < MAX_EVIDENCE:
                self._evidence.append(phrase)
        for flag in text.red_flags:
            if flag not in self._red_flags:
                self._red_flags.append(flag)

    def _build_state(self, stale: bool) -> RiskState:
        # While a warning shows, explain it with the strongest warning heard so
        # far, even if the latest part of the call sounded harmless.
        warning = self._level in (RiskLevel.YELLOW, RiskLevel.RED)
        source = self._strongest_text if warning else self._last_text
        assert source is not None and self._score is not None
        return RiskState(
            level=self._level,
            score=round(self._score, 1),
            scam_type=source.scam_type,
            reason=source.reason,
            next_action=source.next_action,
            evidence=tuple(self._evidence),
            red_flags=tuple(self._red_flags),
            stale=stale,
            breakdown=tuple(self.explain()),
        )
