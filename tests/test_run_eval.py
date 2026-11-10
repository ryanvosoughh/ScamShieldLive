"""4B The evaluation runner, with a fake analyser (no Groq calls)."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.config import Settings
from app.models import RiskLevel, TextSignal

_spec = importlib.util.spec_from_file_location("run_eval", Path(__file__).resolve().parents[1] / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

SETTINGS = Settings.from_env({"DEMO_MODE": "true"})  # thresholds 40 and 70
SCAM = {"id": "s99", "label": "scam", "scam_type": "bank", "tags": ["polite"], "text": "Read me the code."}
FAILED = TextSignal.unknown("Groq rate limit reached")


def verdict(risk, red_flags=()):
    return TextSignal(risk=risk, scam_type="bank", red_flags=tuple(red_flags), reason="r", next_action="n")


class FakeAnalyzer:
    def __init__(self, *signals):
        self.signals = list(signals)
        self.calls = 0

    async def analyze(self, text):
        self.calls += 1
        return self.signals.pop(0)


def check(analyzer, case=SCAM):
    return asyncio.run(run_eval.check_case(case, analyzer, SETTINGS, retry_pause=0))


@pytest.mark.parametrize(
    "label, level, expected",
    [
        ("scam", RiskLevel.RED, "caught"),
        ("scam", RiskLevel.YELLOW, "caught"),
        ("scam", RiskLevel.GREEN, "missed"),
        ("normal", RiskLevel.GREEN, "correct"),
        ("normal", RiskLevel.YELLOW, "false_alarm"),
        ("normal", RiskLevel.UNKNOWN, "unknown"),
    ],
)
def test_each_level_and_label_gives_an_outcome(label, level, expected):
    assert run_eval.outcome(label, level) == expected


def test_the_level_is_what_the_meter_would_show():
    # A polite scam the model scores low, but with a red flag: the scorer makes it red.
    result = check(FakeAnalyzer(verdict(30, ["asks_for_code"])))
    assert (result["risk"], result["level"], result["outcome"]) == (30, "red", "caught")


def test_a_failed_check_is_tried_again():
    analyzer = FakeAnalyzer(FAILED, verdict(85))
    result = check(analyzer)
    assert result["outcome"] == "caught"
    assert result["attempts"] == analyzer.calls == 2


def test_a_check_that_keeps_failing_is_unknown_not_a_miss():
    result = check(FakeAnalyzer(FAILED, FAILED, FAILED))
    assert result["outcome"] == "unknown"
    assert result["error"] == "Groq rate limit reached"
    assert result["attempts"] == run_eval.ATTEMPTS
