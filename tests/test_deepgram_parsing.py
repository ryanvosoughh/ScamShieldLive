from urllib.parse import parse_qs, urlparse

from app.stt.deepgram import DeepgramSTT, parse_message


def results(transcript, is_final, start=1.0, duration=0.5, confidence=0.9):
    """A Deepgram 'Results' message, trimmed to the fields we read."""
    return {
        "type": "Results",
        "is_final": is_final,
        "start": start,
        "duration": duration,
        "channel": {"alternatives": [{"transcript": transcript, "confidence": confidence}]},
    }


def test_final_result_becomes_a_segment():
    segment = parse_message(results("Hi Nana, it's me.", is_final=True, start=2.0, duration=1.5))
    assert segment.text == "Hi Nana, it's me."
    assert segment.is_final is True
    assert segment.start == 2.0
    assert segment.end == 3.5
    assert segment.confidence == 0.9


def test_interim_result_is_marked_not_final():
    assert parse_message(results("Hi Na", is_final=False)).is_final is False


def test_empty_interim_is_dropped():
    assert parse_message(results("", is_final=False)) is None


def test_empty_final_is_kept_so_the_page_can_clear_its_interim_text():
    segment = parse_message(results("", is_final=True))
    assert segment is not None and segment.text == ""


def test_non_result_messages_are_ignored():
    assert parse_message({"type": "Metadata", "request_id": "x"}) is None
    assert parse_message({"type": "SpeechStarted"}) is None
    assert parse_message({"type": "Results", "channel": {"alternatives": []}}) is None


def test_url_requests_the_audio_format_the_browser_sends():
    query = parse_qs(urlparse(DeepgramSTT(api_key="k").build_url()).query)
    assert query["encoding"] == ["linear16"]
    assert query["sample_rate"] == ["16000"]
    assert query["channels"] == ["1"]
    assert query["interim_results"] == ["true"]


def test_api_key_is_not_in_the_url():
    assert "secret" not in DeepgramSTT(api_key="secret").build_url()
