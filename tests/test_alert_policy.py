from app.alerts import WORDING, AlertPolicy, lines_for
from app.models import RiskLevel, RiskState

GREEN, YELLOW, RED, UNKNOWN = RiskLevel.GREEN, RiskLevel.YELLOW, RiskLevel.RED, RiskLevel.UNKNOWN
WARNINGS = (YELLOW, RED)


def at(level):
    return RiskState(level=level, score=None if level is UNKNOWN else 50.0)


def said(policy, *levels):
    """Feed one level per check to the policy; return what was spoken at each one."""
    return [policy.decide(at(level)).spoken for level in levels]


# 3.1 A screen line for every level, a spoken line for each warning


def test_every_level_has_a_screen_line():
    assert set(WORDING) == set(RiskLevel)
    for level in RiskLevel:
        assert lines_for(level).screen


def test_only_the_warnings_have_a_spoken_line():
    assert lines_for(GREEN).spoken is None
    assert lines_for(UNKNOWN).spoken is None
    for level in WARNINGS:
        assert lines_for(level).spoken


def test_every_spoken_warning_says_what_to_do():
    for level in WARNINGS:
        assert "Don't" in lines_for(level).spoken


def test_nothing_ever_says_the_call_is_safe():
    for level in RiskLevel:
        lines = lines_for(level)
        assert "safe" not in f"{lines.screen} {lines.spoken or ''}".lower()


# 3.3 Each warning is said once, on the way up


def test_a_new_warning_is_spoken_once_then_only_shown():
    policy = AlertPolicy()
    assert said(policy, YELLOW, YELLOW, YELLOW) == [lines_for(YELLOW).spoken, None, None]
    assert policy.decide(at(YELLOW)).screen == lines_for(YELLOW).screen  # the screen still shows it


def test_getting_worse_is_spoken_at_once():
    assert said(AlertPolicy(), GREEN, YELLOW, RED) == [None, lines_for(YELLOW).spoken, lines_for(RED).spoken]


def test_stepping_down_and_back_up_says_nothing_new():
    yellow, red = lines_for(YELLOW).spoken, lines_for(RED).spoken
    assert said(AlertPolicy(), YELLOW, GREEN, YELLOW, RED, YELLOW, RED) == [yellow, None, None, red, None, None]


def test_green_is_never_spoken():
    assert said(AlertPolicy(), GREEN, GREEN) == [None, None]


def test_a_failed_check_is_shown_but_never_spoken():
    policy = AlertPolicy()
    assert said(policy, UNKNOWN, GREEN, UNKNOWN) == [None, None, None]
    assert policy.decide(at(UNKNOWN)).screen == lines_for(UNKNOWN).screen


def test_a_failed_check_does_not_hold_back_the_first_warning():
    assert said(AlertPolicy(), UNKNOWN, YELLOW) == [None, lines_for(YELLOW).spoken]
