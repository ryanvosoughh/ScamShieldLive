import pytest

from app.config import ConfigError, Settings


def test_defaults_are_sensible():
    settings = Settings.from_env({"DEEPGRAM_API_KEY": "dg"})
    assert settings.demo_mode is False
    assert settings.live_model == "openai/gpt-oss-120b"
    assert settings.risk_yellow_threshold < settings.risk_red_threshold


def test_live_mode_without_deepgram_key_fails_fast_with_a_helpful_message():
    settings = Settings.from_env({})
    with pytest.raises(ConfigError, match="DEEPGRAM_API_KEY"):
        settings.validate()


def test_demo_mode_needs_no_keys():
    settings = Settings.from_env({"DEMO_MODE": "true"})
    assert settings.validate() == []


def test_missing_groq_key_is_only_a_warning_in_phase_1():
    warnings = Settings.from_env({"DEEPGRAM_API_KEY": "dg"}).validate()
    assert any("GROQ_API_KEY" in w for w in warnings)


def test_a_bad_value_is_reported_by_name():
    with pytest.raises(ConfigError, match="DEMO_MODE must be true or false"):
        Settings.from_env({"DEMO_MODE": "maybe"})
    with pytest.raises(ConfigError, match="PORT must be a whole number"):
        Settings.from_env({"PORT": "eighty"})
    with pytest.raises(ConfigError, match="WINDOW_SECONDS must be a number"):
        Settings.from_env({"WINDOW_SECONDS": "half a minute"})


def test_thresholds_must_be_ordered():
    settings = Settings.from_env({"DEMO_MODE": "true", "RISK_YELLOW_THRESHOLD": "80", "RISK_RED_THRESHOLD": "60"})
    with pytest.raises(ConfigError, match="thresholds"):
        settings.validate()


def test_keys_never_appear_in_repr():
    settings = Settings.from_env({"DEEPGRAM_API_KEY": "secret-dg", "GROQ_API_KEY": "secret-groq"})
    assert "secret" not in repr(settings)


def test_check_spacing_defaults():
    settings = Settings.from_env({"DEMO_MODE": "true"})
    assert settings.analysis_interval_seconds == 12.0
    assert settings.window_seconds == 30.0


def test_checks_too_close_for_groqs_free_tier_are_a_warning():
    close = Settings.from_env({"DEEPGRAM_API_KEY": "dg", "GROQ_API_KEY": "g", "ANALYSIS_INTERVAL_SECONDS": "4"})
    assert any("rate limit" in warning for warning in close.validate())
    spread = Settings.from_env({"DEEPGRAM_API_KEY": "dg", "GROQ_API_KEY": "g"})
    assert spread.validate() == []
