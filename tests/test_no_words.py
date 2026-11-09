"""3.28 The non-English notice: speech that keeps coming through with no words."""
import asyncio
import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.stt.deepgram import DeepgramSTT
from app.stt.no_words import NO_WORDS_CODE, NO_WORDS_MESSAGE, SpeechWithoutWords


def wordless_bursts(detector, count):
    """count bursts of speech that each end with no words; returns what the last final said."""
    change = None
    for _ in range(count):
        detector.speech_started()
        change = detector.final("")
    return change


def test_three_wordless_bursts_in_a_row_show_the_notice_once():
    detector = SpeechWithoutWords(bursts=3)
    assert wordless_bursts(detector, 2) is None
    assert wordless_bursts(detector, 1) is True
    assert wordless_bursts(detector, 5) is None  # already showing
    assert detector.showing


def test_words_reset_the_count_so_a_cough_between_sentences_never_adds_up():
    detector = SpeechWithoutWords(bursts=3)
    for _ in range(10):
        wordless_bursts(detector, 2)
        detector.speech_started()
        assert detector.final("Hello, it's me.") is None
    assert not detector.showing


def test_empty_finals_in_silence_do_not_count():
    detector = SpeechWithoutWords(bursts=3)
    assert [detector.final("") for _ in range(10)] == [None] * 10
    assert not detector.showing


def test_one_burst_with_several_empty_finals_counts_once():
    detector = SpeechWithoutWords(bursts=2)
    detector.speech_started()
    assert [detector.final("") for _ in range(4)] == [None] * 4


def test_words_coming_back_take_the_notice_down():
    detector = SpeechWithoutWords(bursts=3)
    wordless_bursts(detector, 3)
    detector.speech_started()
    assert detector.final("Sorry, can you hear me now?") is False
    assert not detector.showing
    assert wordless_bursts(detector, 3) is True  # and it can come back


def test_bad_settings_are_rejected():
    with pytest.raises(ValueError):
        SpeechWithoutWords(bursts=0)


# Wired into DeepgramSTT


def test_deepgram_is_asked_for_speech_started_events():
    query = parse_qs(urlparse(DeepgramSTT(api_key="k").build_url()).query)
    assert query["vad_events"] == ["true"]


class FakeDeepgramSocket:
    """Plays a list of Deepgram messages to the receive loop, then ends."""

    def __init__(self, messages):
        self.messages = [json.dumps(m) for m in messages]

    def __aiter__(self):
        return self._play()

    async def _play(self):
        for raw in self.messages:
            yield raw


def speech_started():
    return {"type": "SpeechStarted", "channel": [0], "timestamp": 1.0}


def final(text):
    return {
        "type": "Results",
        "is_final": True,
        "start": 0.0,
        "duration": 1.0,
        "channel": {"alternatives": [{"transcript": text, "confidence": 0.99 if text else 0.0}]},
    }


def play_to_deepgram(messages):
    """Run DeepgramSTT's receive loop over these messages; return (notices, finals)."""
    notices, finals = [], []

    async def keep_notice(code, message):
        notices.append((code, message))

    async def keep_segment(segment):
        if segment.is_final:
            finals.append(segment.text)

    async def main():
        stt = DeepgramSTT(api_key="k")
        stt.on_notice(keep_notice)
        stt.on_transcript(keep_segment)
        stt._ws = FakeDeepgramSocket(messages)
        stt._closing = True  # the fake stream just ends; don't report that as a lost connection
        await stt._receive_loop()

    asyncio.run(main())
    return notices, finals


def test_a_foreign_call_as_deepgram_sends_it_raises_the_notice():
    # The shape measured on the French, Spanish and German clips: speech starts, the final is empty.
    notices, finals = play_to_deepgram([speech_started(), final("")] * 3)
    assert notices == [(NO_WORDS_CODE, NO_WORDS_MESSAGE)]
    assert finals == ["", "", ""]  # the empty finals still reach the page, to clear its grey text


def test_an_english_call_as_deepgram_sends_it_raises_nothing():
    lines = ["Hi Nana, it's me.", "I'm in real trouble.", "Please don't tell Mum."]
    notices, _ = play_to_deepgram([m for line in lines for m in (speech_started(), final(line))] + [final("")])
    assert notices == []


def test_the_notice_comes_down_when_words_are_heard():
    notices, _ = play_to_deepgram([speech_started(), final("")] * 3 + [speech_started(), final("Can you hear me?")])
    assert notices == [(NO_WORDS_CODE, NO_WORDS_MESSAGE), (NO_WORDS_CODE, None)]
