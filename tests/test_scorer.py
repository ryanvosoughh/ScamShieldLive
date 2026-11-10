import pytest

from app.config import Settings
from app.models import RiskLevel, TextSignal
from app.scoring import RiskScorer

GREEN, YELLOW, RED, UNKNOWN = RiskLevel.GREEN, RiskLevel.YELLOW, RiskLevel.RED, RiskLevel.UNKNOWN


def words(risk, red_flags=(), evidence=(), scam_type=None, reason=None):
    return TextSignal(
        risk=risk,
        scam_type=scam_type or ("none" if risk < 40 else "grandchild"),
        evidence=tuple(evidence),
        red_flags=tuple(red_flags),
        reason=reason or f"reason for {risk}",
        next_action="No action needed." if risk < 40 else "Hang up.",
    )


FAILED = TextSignal.unknown("Groq rate limit reached")


def unsmoothed(**kwargs):
    """No moving average, so each test sees the rule it is about and nothing else."""
    return RiskScorer(rise=1.0, fall=1.0, **kwargs)


def levels(scorer, *risks):
    return [scorer.update(words(r)).level for r in risks]


# 2.27 Levels from the two thresholds


def test_scores_map_to_levels_at_the_thresholds():
    assert levels(unsmoothed(), 39)[0] is GREEN
    assert levels(unsmoothed(), 40)[0] is YELLOW
    assert levels(unsmoothed(), 69)[0] is YELLOW
    assert levels(unsmoothed(), 70)[0] is RED


def test_thresholds_come_from_settings():
    settings = Settings.from_env({"DEMO_MODE": "true", "RISK_YELLOW_THRESHOLD": "30", "RISK_RED_THRESHOLD": "60"})
    scorer = RiskScorer.from_settings(settings)
    assert (scorer.yellow, scorer.red) == (30, 60)
    assert scorer.update(words(35)).level is YELLOW


def test_bad_settings_are_rejected():
    with pytest.raises(ValueError):
        RiskScorer(yellow_threshold=70, red_threshold=40)
    with pytest.raises(ValueError):
        RiskScorer(rise=0.2, fall=0.5)


# 2.23 Moving average


def test_the_first_check_is_taken_as_it_is():
    assert RiskScorer().update(words(90)).score == 90


def test_the_score_rises_quickly():
    scorer = RiskScorer()
    scorer.update(words(10))
    state = scorer.update(words(90))
    assert state.score == pytest.approx(0.7 * 90 + 0.3 * 10)  # 66
    assert scorer.update(words(90)).level is RED  # one more check and it is red


def test_the_score_falls_slowly():
    scorer = RiskScorer()
    scorer.update(words(60))
    assert scorer.update(words(0)).score == pytest.approx(0.7 * 60)  # 42, still yellow


def test_one_odd_reply_does_not_make_the_meter_jump():
    scorer = RiskScorer()
    scorer.update(words(10))
    scorer.update(words(10))
    assert scorer.update(words(45)).level is GREEN  # 0.7 * 45 + 0.3 * 10 = 34.5


# Red flags skip the average


def test_a_red_flag_goes_straight_to_red():
    scorer = RiskScorer()
    scorer.update(words(10))
    state = scorer.update(words(75, red_flags=["asks_for_code"]))  # the average alone would be 55.5
    assert state.level is RED
    assert state.score == 70


# 2.24 Hysteresis


def test_the_level_does_not_flicker_around_a_threshold():
    assert levels(unsmoothed(), 41, 39, 41, 38, 42) == [YELLOW] * 5


def test_a_level_is_left_once_the_score_is_clearly_below_it():
    assert levels(unsmoothed(), 45, 36, 34) == [YELLOW, YELLOW, GREEN]
    assert levels(unsmoothed(), 75, 66, 64) == [RED, RED, YELLOW]


def test_going_up_needs_no_margin():
    assert levels(unsmoothed(), 10, 40, 70) == [GREEN, YELLOW, RED]


def test_once_red_the_call_never_shows_green_again():
    assert levels(unsmoothed(), 85, 5, 0) == [RED, YELLOW, YELLOW]


def test_a_warning_keeps_the_reason_for_the_strongest_warning():
    scorer = unsmoothed()
    scorer.update(words(85, reason="They want gift cards and secrecy."))
    state = scorer.update(words(5, reason="Small talk about the weather."))
    assert state.level is YELLOW
    assert state.reason == "They want gift cards and secrecy."
    assert state.next_action == "Hang up."


# 2.26 UNKNOWN never drops to GREEN


def test_before_any_check_the_level_is_unknown():
    scorer = RiskScorer()
    assert scorer.state.level is UNKNOWN
    assert scorer.update(FAILED).level is UNKNOWN


def test_a_failed_check_after_green_is_unknown_not_green():
    scorer = RiskScorer()
    scorer.update(words(10))
    state = scorer.update(FAILED)
    assert state.level is UNKNOWN
    assert state.score is None
    assert state.stale is True


def test_a_failed_check_keeps_a_warning_on_screen():
    scorer = RiskScorer()
    scorer.update(words(90, reason="Gift cards."))
    state = scorer.update(FAILED)
    assert state.level is RED
    assert state.reason == "Gift cards."
    assert state.stale is True


def test_the_next_good_check_clears_stale():
    scorer = RiskScorer()
    scorer.update(words(10))
    scorer.update(FAILED)
    state = scorer.update(words(10))
    assert state.level is GREEN
    assert state.stale is False


# Evidence and red flags for the whole call


def test_evidence_and_red_flags_build_up_over_the_call_without_repeats():
    scorer = unsmoothed()
    scorer.update(words(60, evidence=["don't tell Mum"], red_flags=["unusual_payment"]))
    state = scorer.update(words(90, evidence=["don't tell Mum", "gift cards"], red_flags=["unusual_payment"]))
    assert state.evidence == ("don't tell Mum", "gift cards")
    assert state.red_flags == ("unusual_payment",)


# 2.28 explain()


def test_explain_gives_the_words_and_the_result():
    scorer = RiskScorer()
    assert scorer.state.breakdown == ("Words: not checked yet",)
    scorer.update(words(90, red_flags=["asks_for_code"]))
    lines = scorer.explain()
    assert lines == [
        "Words: 90/100, grandchild, red flags: asks_for_code",
        "Smoothed score: 90/100, level red",
    ]
    assert scorer.state.breakdown == tuple(lines)


def test_explain_says_why_a_check_gave_no_result():
    scorer = RiskScorer()
    scorer.update(FAILED)
    assert scorer.explain()[0] == "Words: no result (Groq rate limit reached)"
