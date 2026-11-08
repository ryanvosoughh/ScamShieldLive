"""Demo mode: the scripts, ReplaySTT, the scripted analyser, and whole demo calls (no keys, no network)."""
import asyncio
import json

import pytest

from app.demo import DemoError, ScriptedAnalyzer, list_scenarios, load_scenario
from app.demo import scenarios as scenarios_module
from app.session import CallSession
from app.stt import ReplaySTT

FAST = 200.0  # replay speed for tests: a 45 s call plays in about a quarter of a second


# 2.34, 2.35 The scripts


def test_the_three_demo_calls_are_there():
    assert set(list_scenarios()) >= {"grandchild_scam", "bank_scam", "normal_call"}


@pytest.mark.parametrize("scenario_id", list_scenarios())
def test_every_script_loads_with_timed_lines_in_order(scenario_id):
    scenario = load_scenario(scenario_id)
    assert scenario.lines
    previous_end = 0.0
    for line in scenario.lines:
        assert line.text
        assert line.start >= previous_end
        assert line.end > line.start
        previous_end = line.end


def test_an_unknown_name_is_refused_and_never_used_as_a_path():
    for bad in ["nope", "../../.env", "calls/bank_scam", ""]:
        with pytest.raises(DemoError, match="Choose one of"):
            load_scenario(bad)


def test_a_broken_script_is_refused_when_it_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(scenarios_module, "CALLS_DIR", tmp_path)
    broken = {
        "title": "Broken",
        "kind": "scam",
        "description": "Evidence that is never said.",
        "lines": [
            {
                "start": 0,
                "end": 2,
                "text": "Hello there.",
                "verdict": {
                    "risk": 90,
                    "scam_type": "bank",
                    "red_flags": [],
                    "evidence": ["read me the code"],
                    "reason": "x",
                    "next_action": "y",
                },
            }
        ],
    }
    (tmp_path / "broken.json").write_text(json.dumps(broken))
    load_scenario.cache_clear()
    try:
        with pytest.raises(DemoError, match="never said"):
            load_scenario("broken")
    finally:
        load_scenario.cache_clear()


# 2.36 ReplaySTT


def collect_replay(scenario_id, speed=FAST):
    async def main():
        stt = ReplaySTT(load_scenario(scenario_id), speed=speed)
        segments = []

        async def keep(segment):
            segments.append(segment)

        stt.on_transcript(keep)
        await stt.connect()
        await asyncio.wait_for(stt.finished.wait(), timeout=5)
        await stt.close()
        return segments

    return asyncio.run(main())


def test_replay_says_every_line_as_a_final_with_the_script_times():
    scenario = load_scenario("bank_scam")
    finals = [s for s in collect_replay("bank_scam") if s.is_final]
    assert [s.text for s in finals] == [line.text for line in scenario.lines]
    assert [(s.start, s.end) for s in finals] == [(line.start, line.end) for line in scenario.lines]


def test_replay_shows_interim_words_before_each_final_like_live_speech():
    segments = collect_replay("normal_call")
    first_final = next(i for i, s in enumerate(segments) if s.is_final)
    interims = segments[:first_final]
    assert interims and all(not s.is_final for s in interims)
    assert segments[first_final].text.startswith(interims[-1].text)


def test_replay_keeps_to_real_time():
    async def main():
        stt = ReplaySTT(load_scenario("normal_call"), speed=100)
        await stt.connect()
        started = asyncio.get_running_loop().time()
        await asyncio.wait_for(stt.finished.wait(), timeout=5)
        return asyncio.get_running_loop().time() - started

    took = asyncio.run(main())
    assert took == pytest.approx(load_scenario("normal_call").duration / 100, abs=0.1)


def test_closing_stops_the_replay_early():
    async def main():
        stt = ReplaySTT(load_scenario("bank_scam"), speed=1.0)
        await stt.connect()
        await asyncio.sleep(0.05)
        await stt.close()
        return stt.finished.is_set()

    assert asyncio.run(main()) is False


# 2.38 The scripted analyser


def test_the_verdict_follows_the_newest_line_heard():
    scenario = load_scenario("grandchild_scam")
    analyzer = ScriptedAnalyzer(scenario)
    lines = [line.text for line in scenario.lines]

    early = asyncio.run(analyzer.analyze(" ".join(lines[:1])))
    bail = asyncio.run(analyzer.analyze(" ".join(lines[:4])))
    cards = asyncio.run(analyzer.analyze(" ".join(lines[:7])))
    assert early.risk == 5 and early.scam_type == "none"
    assert bail.risk == 60 and bail.evidence == ("pay bail today",)
    assert cards.risk == 95 and cards.red_flags == ("unusual_payment",)


def test_a_line_without_its_own_verdict_keeps_the_one_before():
    scenario = load_scenario("grandchild_scam")
    lines = [line.text for line in scenario.lines]
    analyzer = ScriptedAnalyzer(scenario)
    # Line 5 ("Oh no! Are you hurt?") has no verdict, so line 4's still stands.
    assert asyncio.run(analyzer.analyze(" ".join(lines[:5]))).risk == 60


def test_scripted_evidence_is_only_quoted_while_it_is_in_the_window():
    scenario = load_scenario("grandchild_scam")
    analyzer = ScriptedAnalyzer(scenario)
    only_the_last_lines = " ".join(line.text for line in scenario.lines[5:])
    signal = asyncio.run(analyzer.analyze(only_the_last_lines))
    assert "pay bail today" not in signal.evidence  # said earlier, now out of the window
    assert "Please don't tell Mum" in signal.evidence


# Whole demo calls through the real window, check loop and scorer


def play_whole_call(scenario_id):
    """Run a demo call the way the server does, but fast. Returns the risk states sent."""
    sent = []

    async def send(message):
        sent.append(message)

    async def main():
        scenario = load_scenario(scenario_id)
        stt = ReplaySTT(scenario, speed=FAST)
        session = CallSession(
            stt, send, analyzer=ScriptedAnalyzer(scenario), check_interval=4 / FAST, checks_per_minute=1000
        )
        await session.start()
        await asyncio.wait_for(stt.finished.wait(), timeout=5)
        await session.end()

    asyncio.run(main())
    return [m for m in sent if m["type"] == "state"]


def test_the_grandchild_scam_ends_red_with_a_reason():
    states = play_whole_call("grandchild_scam")
    assert states[0]["level"] == "green"
    assert states[-1]["level"] == "red"
    assert "gift cards" in states[-1]["reason"]
    assert "unusual_payment" in states[-1]["red_flags"]


def test_the_bank_scam_ends_red_after_the_code_request():
    states = play_whole_call("bank_scam")
    assert states[-1]["level"] == "red"
    assert "asks_for_code" in states[-1]["red_flags"]


def test_the_normal_call_stays_green_throughout():
    states = play_whole_call("normal_call")
    assert states
    assert {s["level"] for s in states} == {"green"}


def test_the_bank_scam_warns_yellow_before_it_turns_red():
    levels = [s["level"] for s in play_whole_call("bank_scam")]
    first_yellow, first_red = levels.index("yellow"), levels.index("red")
    assert first_yellow < first_red
