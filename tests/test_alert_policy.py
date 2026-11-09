import pytest

from app.alerts import WORDING, AlertPolicy, lines_for
from app.models import Persona, RiskLevel, RiskState

GREEN, YELLOW, RED, UNKNOWN = RiskLevel.GREEN, RiskLevel.YELLOW, RiskLevel.RED, RiskLevel.UNKNOWN
STANDARD, GRAN = Persona.STANDARD, Persona.GRAN
WARNINGS = (YELLOW, RED, UNKNOWN)


def at(level):
    return RiskState(level=level, score=None if level is UNKNOWN else 50.0)


def said(policy, *steps, persona=STANDARD, quiet_mode=False):
    """Feed (seconds, level) steps to the policy; return what was spoken at each one."""
    return [policy.decide(at(level), persona, quiet_mode, now=t).spoken for t, level in steps]


def word_count(line):
    return len(line.split()) if line else 0


# 3.1 A screen line and a spoken line per level


@pytest.mark.parametrize("persona", list(Persona))
def test_every_level_has_wording_in_every_persona(persona):
    assert set(WORDING[persona]) == set(RiskLevel)
    for level in RiskLevel:
        assert lines_for(level, persona).screen


@pytest.mark.parametrize("persona", list(Persona))
def test_green_is_never_spoken_and_every_warning_is(persona):
    assert lines_for(GREEN, persona).spoken is None
    for level in WARNINGS:
        assert lines_for(level, persona).spoken


@pytest.mark.parametrize("persona", list(Persona))
def test_every_spoken_warning_says_what_to_do(persona):
    for level in WARNINGS:
        assert "Don't" in lines_for(level, persona).spoken


def test_nothing_ever_says_the_call_is_safe():
    for persona in Persona:
        for level in RiskLevel:
            lines = lines_for(level, persona)
            assert "safe" not in f"{lines.screen} {lines.spoken or ''}".lower()


# 3.2 Gran wording is shorter and calmer


@pytest.mark.parametrize("level", list(RiskLevel))
def test_gran_lines_are_never_longer_than_standard(level):
    standard, gran = lines_for(level, STANDARD), lines_for(level, GRAN)
    assert word_count(gran.screen) <= word_count(standard.screen)
    assert word_count(gran.spoken) <= word_count(standard.spoken)


def test_gran_wording_avoids_alarming_words():
    for level in RiskLevel:
        lines = lines_for(level, GRAN)
        text = f"{lines.screen} {lines.spoken or ''}".lower()
        assert "scam" not in text
        assert "warning" not in text


def test_the_policy_uses_the_persona_wording():
    assert AlertPolicy().decide(at(RED), GRAN, now=0).spoken == lines_for(RED, GRAN).spoken
    assert AlertPolicy().decide(at(RED), STANDARD, now=0).spoken == lines_for(RED, STANDARD).spoken


# 3.3 Cooldown: the same alert does not repeat


def test_a_new_warning_is_spoken_once_then_only_shown():
    policy = AlertPolicy(cooldown_seconds=60)
    assert said(policy, (0, YELLOW), (4, YELLOW), (8, YELLOW)) == [lines_for(YELLOW).spoken, None, None]
    assert policy.decide(at(YELLOW), now=12).screen == lines_for(YELLOW).screen  # the screen still shows it


def test_the_same_warning_is_said_again_after_the_cooldown():
    policy = AlertPolicy(cooldown_seconds=60)
    red = lines_for(RED).spoken
    assert said(policy, (0, RED), (59, RED), (60, RED), (100, RED)) == [red, None, red, None]


def test_getting_worse_is_spoken_at_once_even_inside_the_cooldown():
    policy = AlertPolicy(cooldown_seconds=60)
    assert said(policy, (0, YELLOW), (4, RED)) == [lines_for(YELLOW).spoken, lines_for(RED).spoken]


def test_a_step_down_is_never_spoken():
    policy = AlertPolicy(cooldown_seconds=60)
    assert said(policy, (0, RED), (4, YELLOW), (200, YELLOW)) == [lines_for(RED).spoken, None, None]


def test_back_up_after_a_step_down_waits_for_the_cooldown():
    policy = AlertPolicy(cooldown_seconds=60)
    red = lines_for(RED).spoken
    assert said(policy, (0, RED), (4, YELLOW), (8, RED), (61, RED)) == [red, None, None, red]


def test_green_is_never_spoken_in_a_call():
    assert said(AlertPolicy(), (0, GREEN), (100, GREEN)) == [None, None]


def test_a_check_that_stops_working_is_spoken_after_green():
    policy = AlertPolicy(cooldown_seconds=60)
    assert said(policy, (0, GREEN), (4, UNKNOWN), (8, UNKNOWN)) == [None, lines_for(UNKNOWN).spoken, None]


def test_switching_persona_does_not_repeat_the_same_warning():
    policy = AlertPolicy(cooldown_seconds=60)
    policy.decide(at(RED), STANDARD, now=0)
    alert = policy.decide(at(RED), GRAN, now=4)
    assert alert.spoken is None
    assert alert.screen == lines_for(RED, GRAN).screen


def test_a_negative_cooldown_is_rejected():
    with pytest.raises(ValueError):
        AlertPolicy(cooldown_seconds=-1)


# 3.4 Quiet mode: screen only


def test_quiet_mode_never_speaks_but_still_shows_the_warning():
    policy = AlertPolicy()
    assert said(policy, (0, YELLOW), (4, RED), (100, RED), quiet_mode=True) == [None, None, None]
    assert policy.decide(at(RED), quiet_mode=True, now=104).screen == lines_for(RED).screen


def test_turning_quiet_mode_off_speaks_the_warning_that_is_up():
    policy = AlertPolicy(cooldown_seconds=60)
    said(policy, (0, RED), quiet_mode=True)
    assert said(policy, (4, RED), quiet_mode=False) == [lines_for(RED).spoken]
