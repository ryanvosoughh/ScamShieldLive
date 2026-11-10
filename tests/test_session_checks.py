"""CallSession's scam-check loop, with a fake analyser (no network, no keys)."""
import asyncio
import json
import time

from app.alerts import lines_for
from app.models import Persona, RiskLevel, TextSignal, TranscriptSegment
from app.session import CallSession, state_message
from app.stt import SpeechToTextClient

SCAM_LINE = "Hi Nana it's me, I need bail money today, please don't tell Mum."


class SilentSTT(SpeechToTextClient):
    """Does nothing; the tests hand transcript segments to the session directly."""

    async def connect(self):
        pass

    async def send_audio(self, chunk):
        pass

    async def close(self):
        pass


class FakeAnalyzer:
    def __init__(self, risk=90, delay=0.0, signal=None, signals=None):
        self.risk = risk
        self.delay = delay
        self.signal = signal
        self.signals = list(signals or [])  # given out one per check, before falling back to signal/risk
        self.texts = []  # what each check was given
        self.started = []  # when each check started
        self.running = 0
        self.most_at_once = 0

    async def analyze(self, text):
        self.texts.append(text)
        self.started.append(time.monotonic())
        self.running += 1
        self.most_at_once = max(self.most_at_once, self.running)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.running -= 1
        if self.signals:
            return self.signals.pop(0)
        return self.signal or TextSignal(
            risk=self.risk,
            scam_type="grandchild",
            evidence=("don't tell Mum",),
            reason="They want money fast and want it kept secret.",
            next_action="Hang up and call them back on a number you already have.",
        )


def final(text, start=0.0, end=3.0):
    return TranscriptSegment(text, True, start, end, 0.9)


def run_call(scenario, analyzer=None, interval=0.2, per_minute=5, minute=60.0):
    """Start a session, run the scenario against it, end it, and return what was sent."""
    sent = []

    async def send(message):
        sent.append(message)

    async def main():
        session = CallSession(
            SilentSTT(),
            send,
            analyzer=analyzer,
            check_interval=interval,
            checks_per_minute=per_minute,
            rate_window_seconds=minute,
        )
        await session.start()
        try:
            await scenario(session)
        finally:
            await session.end()
        return session

    session = asyncio.run(main())
    return session, sent


def states(sent):
    return [m for m in sent if m["type"] == "state"]


# 2.31 New final speech starts a check; 2.32 the state goes to the browser


def test_new_final_speech_starts_a_check_and_sends_the_state():
    analyzer = FakeAnalyzer(risk=90)

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE))
        await asyncio.sleep(0.05)

    _, sent = run_call(scenario, analyzer)
    assert analyzer.texts == [SCAM_LINE]
    [state] = states(sent)
    assert state["level"] == "red"
    assert state["reason"] == "They want money fast and want it kept secret."
    assert state["evidence"] == ["don't tell Mum"]


def test_interim_text_and_very_short_speech_do_not_use_a_model_call():
    analyzer = FakeAnalyzer()

    async def scenario(session):
        await session.on_transcript(TranscriptSegment(SCAM_LINE, False, 0.0, 3.0, 0.5))  # still a guess
        await session.on_transcript(final("Hello?"))  # final, but too short to judge
        await asyncio.sleep(0.05)

    _, sent = run_call(scenario, analyzer)
    assert analyzer.texts == []
    assert states(sent) == []


# Spacing for the free tier


def test_checks_are_spaced_out_by_the_interval():
    analyzer = FakeAnalyzer()

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE, 0, 3))
        await asyncio.sleep(0.05)
        await session.on_transcript(final("Go to the shop and buy the gift cards now.", 3, 6))
        await asyncio.sleep(0.45)

    run_call(scenario, analyzer, interval=0.3)
    assert len(analyzer.started) == 2
    assert analyzer.started[1] - analyzer.started[0] >= 0.29


def test_no_more_checks_than_the_per_minute_cap():
    analyzer = FakeAnalyzer()

    async def scenario(session):
        for n in range(3):
            await session.on_transcript(final(f"{SCAM_LINE} Line {n}.", 3 * n, 3 * n + 3))
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)

    # A pretend "minute" of 0.4 s with room for 2 checks, and no gap between checks.
    run_call(scenario, analyzer, interval=0.0, per_minute=2, minute=0.4)
    assert len(analyzer.started) == 3
    assert analyzer.started[1] - analyzer.started[0] < 0.2  # the second fits in the minute
    assert analyzer.started[2] - analyzer.started[0] >= 0.39  # the third waits for the first to age out


def test_silence_costs_nothing():
    analyzer = FakeAnalyzer()

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE))
        await asyncio.sleep(0.5)  # more than two intervals with no new speech

    run_call(scenario, analyzer, interval=0.2)
    assert len(analyzer.texts) == 1


def test_speech_during_a_check_waits_and_checks_never_overlap():
    analyzer = FakeAnalyzer(delay=0.2)

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE, 0, 3))
        await asyncio.sleep(0.05)  # the first check is now running
        for n in range(3):
            await session.on_transcript(final(f"More words number {n} about the money you must send.", 3 + n, 4 + n))
        await asyncio.sleep(0.6)

    session, _ = run_call(scenario, analyzer, interval=0.0)
    assert analyzer.most_at_once == 1
    assert len(analyzer.texts) == 2  # the three lines were checked together, once
    assert "number 2" in analyzer.texts[1]
    assert session.checks == 2


# Failure and shutdown


def test_a_failed_check_sends_unknown_not_safe():
    analyzer = FakeAnalyzer(signal=TextSignal.unknown("Groq rate limit reached"))

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE))
        await asyncio.sleep(0.05)

    _, sent = run_call(scenario, analyzer)
    [state] = states(sent)
    assert state["level"] == "unknown"
    assert state["breakdown"][0] == "Words: no result (Groq rate limit reached)"


FAILED = TextSignal.unknown("Groq rate limit reached")
ANSWERED = TextSignal(risk=10, scam_type="none", reason="Small talk.", next_action="No action needed.")


def notices(sent):
    return [(m["code"], m["message"]) for m in sent if m["type"] == "notice"]


def check_each_line(analyzer, lines):
    """One check per line, each on new speech."""

    async def scenario(session):
        for n in range(lines):
            await session.on_transcript(final(f"{SCAM_LINE} Line {n}.", 3 * n, 3 * n + 3))
            await asyncio.sleep(0.03)

    return run_call(scenario, analyzer, interval=0.0)


def test_one_failed_check_shows_on_the_meter_but_raises_no_banner():
    _, sent = check_each_line(FakeAnalyzer(signals=[FAILED, ANSWERED]), 2)
    assert notices(sent) == []


def test_two_failed_checks_in_a_row_raise_the_banner_once_with_the_reason():
    _, sent = check_each_line(FakeAnalyzer(signals=[FAILED, FAILED, FAILED]), 3)
    [(code, message)] = notices(sent)
    assert code == "analysis_unavailable"
    assert message.startswith("The scam check isn't answering")
    assert message.endswith("(Groq rate limit reached)")


def test_the_banner_comes_down_when_a_check_answers_again():
    session, sent = check_each_line(FakeAnalyzer(signals=[FAILED, FAILED, ANSWERED]), 3)
    assert [message is None for _, message in notices(sent)] == [False, True]
    assert session.checks == 3


def test_notices_from_speech_to_text_reach_the_browser():
    async def scenario(session):
        await session._stt._emit_notice("no_words", "Speech is coming through, but no words are being recognised.")

    _, sent = run_call(scenario)
    assert notices(sent) == [("no_words", "Speech is coming through, but no words are being recognised.")]


def test_ending_the_call_stops_a_check_in_flight():
    analyzer = FakeAnalyzer(delay=1.0)

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE))
        await asyncio.sleep(0.05)  # check started; end() comes before it finishes

    started = time.monotonic()
    session, sent = run_call(scenario, analyzer)
    assert time.monotonic() - started < 0.5  # did not wait for the slow check
    assert states(sent) == []
    assert session.checks == 0


def test_without_an_analyser_there_are_no_checks():
    async def scenario(session):
        assert session.analysis_on is False
        await session.on_transcript(final(SCAM_LINE))
        assert await session.tick() is None

    _, sent = run_call(scenario, analyzer=None)
    assert states(sent) == []
    assert [m["type"] for m in sent] == ["transcript"]


def test_the_state_message_is_plain_json():
    analyzer = FakeAnalyzer()

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE))
        await asyncio.sleep(0.05)

    _, sent = run_call(scenario, analyzer)
    [state] = states(sent)
    assert json.loads(json.dumps(state)) == state
    assert set(state) == {
        "type", "level", "score", "scam_type", "reason", "next_action",
        "evidence", "red_flags", "stale", "breakdown",
        "headline", "speak",
    }


# The alert policy: the meter's headline and the spoken warning


def test_a_new_warning_comes_with_its_headline_and_a_line_to_say():
    analyzer = FakeAnalyzer(risk=90)

    async def scenario(session):
        await session.on_transcript(final(SCAM_LINE))
        await asyncio.sleep(0.05)

    _, sent = run_call(scenario, analyzer)
    [state] = states(sent)
    assert state["headline"] == lines_for(RiskLevel.RED).screen
    assert state["speak"] == lines_for(RiskLevel.RED).spoken


def test_the_same_warning_is_not_said_again_on_the_next_check():
    _, sent = check_each_line(FakeAnalyzer(risk=90), 3)
    spoken = [s["speak"] for s in states(sent)]
    assert spoken == [lines_for(RiskLevel.RED).spoken, None, None]
    assert {s["headline"] for s in states(sent)} == {lines_for(RiskLevel.RED).screen}  # still on screen


def test_quiet_mode_and_persona_reach_the_alert():
    async def scenario(session):
        session.persona = Persona.GRAN
        session.quiet_mode = True
        await session.on_transcript(final(SCAM_LINE))
        await asyncio.sleep(0.05)

    _, sent = run_call(scenario, FakeAnalyzer(risk=90))
    [state] = states(sent)
    assert state["headline"] == lines_for(RiskLevel.RED, Persona.GRAN).screen
    assert state["speak"] is None


def test_state_message_uses_the_level_name():
    from app.models import RiskLevel, RiskState

    assert state_message(RiskState(level=RiskLevel.YELLOW, score=50.0))["level"] == "yellow"
