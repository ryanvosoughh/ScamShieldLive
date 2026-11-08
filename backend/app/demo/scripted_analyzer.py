"""ScriptedAnalyzer: the scam check for keyless demos.

It has the same analyze() as ScamAnalyzer, so the window, check loop, scorer
and screen all run exactly as in a live call. Only the verdicts come from the
script instead of the model: the verdict in force after the newest scripted
line that appears in the transcript window.
"""
from __future__ import annotations

from app.analysis.analyzer import normalised_words, phrases_from_transcript
from app.demo.scenarios import Scenario, Verdict
from app.models import TextSignal

NOTHING_YET = Verdict(
    risk=5,
    scam_type="none",
    red_flags=(),
    evidence=(),
    reason="Nothing worrying so far.",
    next_action="No action needed.",
)


class ScriptedAnalyzer:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        # The verdict in force after each line: a line without its own verdict
        # keeps the one before it.
        self._in_force: list[Verdict] = []
        current = NOTHING_YET
        for line in scenario.lines:
            current = line.verdict or current
            self._in_force.append(current)

    async def analyze(self, window_text: str) -> TextSignal:
        heard = f" {normalised_words(window_text)} "
        newest = None
        for index, line in enumerate(self.scenario.lines):
            if f" {normalised_words(line.text)} " in heard:
                newest = index
        verdict = NOTHING_YET if newest is None else self._in_force[newest]
        return TextSignal(
            risk=verdict.risk,
            scam_type=verdict.scam_type,
            # Only quote what is still in the window, as the live check does.
            evidence=phrases_from_transcript(list(verdict.evidence), window_text),
            red_flags=verdict.red_flags,
            reason=verdict.reason,
            next_action=verdict.next_action,
        )
