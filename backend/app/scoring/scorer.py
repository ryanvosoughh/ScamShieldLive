"""RiskScorer: turns each round of signals into the level the risk meter shows.

The rules, in the order they are applied:

1. Combine the signals that are available, with weights. The words carry most
   of the weight; tone and voice are weak signals. They can raise the score
   but never pull it below what the words show: a calm voice doesn't make a
   request safe. Without a verdict on the words there is no verdict at all.
2. Smooth with a moving average so one odd reply doesn't make the meter jump.
   It rises quickly and falls slowly: warnings come fast, calm comes slowly.
3. A red flag in the words goes straight to red, without waiting for the average.
4. Hysteresis: a level is only left once the score is clearly below its
   threshold, so the meter doesn't flicker when the score hovers near a line.
5. Once a call has been red it never shows green again; it can ease to yellow.
6. A failed check never shows as safe. A warning already on screen stays; with
   no warning yet, the meter shows UNKNOWN.
"""
from __future__ import annotations

from app.config import Settings
from app.models import RiskLevel, RiskState, TextSignal, ToneSignal, VoiceSignal

# How much each signal counts when they are combined (rule 1).
WEIGHTS: dict[str, float] = {"text": 0.75, "tone": 0.15, "voice": 0.10}
LABELS: dict[str, str] = {"text": "Words", "tone": "Tone", "voice": "Voice"}

# Moving average (rule 2): how much a new score counts against the running one.
RISE = 0.7  # when the new score is higher
FALL = 0.3  # when it is lower
HYSTERESIS_POINTS = 5.0  # rule 4: how far below a threshold the score must fall
DISAGREEMENT_POINTS = 40  # signals this far apart are reported as disagreeing
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
        self._latest: dict[str, TextSignal | ToneSignal | VoiceSignal | None] = {}
        self._last_text: TextSignal | None = None  # newest text check that worked
        self._strongest_text: TextSignal | None = None  # highest-risk text check so far
        self._evidence: list[str] = []
        self._red_flags: list[str] = []
        self.state = RiskState(level=RiskLevel.UNKNOWN, score=None, breakdown=tuple(self.explain()))

    @classmethod
    def from_settings(cls, settings: Settings) -> RiskScorer:
        return cls(settings.risk_yellow_threshold, settings.risk_red_threshold)

    def update(
        self,
        text: TextSignal | None = None,
        tone: ToneSignal | None = None,
        voice: VoiceSignal | None = None,
    ) -> RiskState:
        """Take the latest signals (any may be missing) and return the new state."""
        self._latest = {"text": text, "tone": tone, "voice": voice}
        risks = {
            name: signal.risk
            for name, signal in self._latest.items()
            if signal is not None and signal.risk is not None
        }
        disagreement = self._disagreement(risks)

        if "text" not in risks:
            return self._no_verdict(disagreement)

        assert text is not None  # it has a risk, so it is there
        self._remember(text)
        combined = self._combine(risks)
        if self._score is None:
            self._score = combined
        else:
            weight = self.rise if combined > self._score else self.fall
            self._score = weight * combined + (1 - weight) * self._score
        if text.red_flags:
            self._score = max(self._score, float(self.red))  # rule 3

        self._level = self._next_level(self._score)
        if self._level is RiskLevel.RED:
            self._been_red = True
        elif self._been_red and self._level is RiskLevel.GREEN:
            self._level = RiskLevel.YELLOW  # rule 5

        self.state = self._build_state(disagreement=disagreement, stale=False)
        return self.state

    def explain(self) -> list[str]:
        """A short line per signal, then the smoothed score and level."""
        lines = []
        for name, label in LABELS.items():
            signal = self._latest.get(name)
            if signal is None:
                lines.append(f"{label}: not measured")
            elif signal.risk is None:
                why = getattr(signal, "error", None) or getattr(signal, "detail", "") or "no result"
                lines.append(f"{label}: no result ({why})")
            else:
                line = f"{label}: {signal.risk}/100, weight {WEIGHTS[name]:.2f}"
                if isinstance(signal, TextSignal):
                    line += f", {signal.scam_type}"
                    if signal.red_flags:
                        line += f", red flags: {', '.join(signal.red_flags)}"
                elif signal.detail:
                    line += f", {signal.detail}"
                lines.append(line)
        if self._score is not None:
            lines.append(f"Smoothed score: {self._score:.0f}/100, level {self._level.value}")
        return lines

    def _combine(self, risks: dict[str, int]) -> float:
        """Rule 1: a weighted average of what is available, never below the words."""
        weighted = sum(WEIGHTS[name] * risk for name, risk in risks.items()) / sum(
            WEIGHTS[name] for name in risks
        )
        return max(float(risks["text"]), weighted)

    def _next_level(self, score: float) -> RiskLevel:
        """Thresholds with hysteresis (rule 4): go up at once, come down only when clearly below."""
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

    def _no_verdict(self, disagreement: str | None) -> RiskState:
        """Rule 6: the words couldn't be checked this time."""
        if self._level in (RiskLevel.YELLOW, RiskLevel.RED):
            # Keep the warning on screen, marked as not up to date.
            self.state = self._build_state(disagreement=disagreement, stale=True)
        else:
            # Nothing has warned yet, but we can't say it is still safe.
            self._level = RiskLevel.UNKNOWN
            self.state = RiskState(
                level=RiskLevel.UNKNOWN,
                score=None,
                evidence=tuple(self._evidence),
                red_flags=tuple(self._red_flags),
                disagreement=disagreement,
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

    def _build_state(self, disagreement: str | None, stale: bool) -> RiskState:
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
            disagreement=disagreement,
            stale=stale,
            breakdown=tuple(self.explain()),
        )

    @staticmethod
    def _disagreement(risks: dict[str, int]) -> str | None:
        """Report when tone or voice point a very different way from the words."""
        text = risks.get("text")
        if text is None:
            return None
        notes = [
            f"The words point to {text}/100 but the {LABELS[name].lower()} points to {risks[name]}/100."
            for name in ("tone", "voice")
            if name in risks and abs(text - risks[name]) >= DISAGREEMENT_POINTS
        ]
        return " ".join(notes) or None
