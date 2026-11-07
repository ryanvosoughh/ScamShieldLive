import pytest

from app.analysis import TranscriptWindow
from app.models import TranscriptSegment


def seg(text: str, start: float, end: float, is_final: bool = True) -> TranscriptSegment:
    return TranscriptSegment(text=text, is_final=is_final, start=start, end=end, confidence=0.9)


# 2.1 add() stores final segments with their timestamps


def test_only_final_segments_with_text_are_stored():
    window = TranscriptWindow()
    assert window.add(seg("Hi Nana it's me", 0.0, 1.5)) is True
    assert window.add(seg("I'm in real", 1.5, 2.2, is_final=False)) is False  # interim guess
    assert window.add(seg("", 2.2, 2.5)) is False  # empty final that clears the interim line
    assert window.add(seg("   ", 2.5, 2.8)) is False
    assert window.text() == "Hi Nana it's me"


def test_text_keeps_the_order_segments_were_spoken_in():
    window = TranscriptWindow()
    window.add(seg("I'm in trouble.", 0.0, 1.0))
    window.add(seg("Don't tell Mum.", 1.0, 2.0))
    assert window.text() == "I'm in trouble. Don't tell Mum."


# 2.2 text(last_seconds) returns only the recent part


def test_old_segments_fall_out_of_the_window():
    window = TranscriptWindow(window_seconds=30)
    window.add(seg("Hello, how are you?", 0.0, 2.0))
    window.add(seg("I need you to buy gift cards.", 40.0, 43.0))
    # Newest text ends at 43 s, so the window covers 13-43 s.
    assert window.text() == "I need you to buy gift cards."


def test_a_segment_that_crosses_the_cut_off_is_kept_whole():
    window = TranscriptWindow(window_seconds=30)
    window.add(seg("Please don't tell your daughter.", 10.0, 14.0))
    window.add(seg("Read me the numbers.", 41.0, 43.0))
    # Cut-off is 13 s; the first segment ends at 14 s, so it stays, in full.
    assert window.text() == "Please don't tell your daughter. Read me the numbers."


def test_last_seconds_can_be_narrower_than_the_window():
    window = TranscriptWindow(window_seconds=30)
    window.add(seg("It's your bank.", 0.0, 2.0))
    window.add(seg("Move your money to a safe account.", 8.0, 11.0))
    assert window.text(last_seconds=5) == "Move your money to a safe account."


def test_now_on_the_audio_clock_drops_text_after_a_long_silence():
    window = TranscriptWindow(window_seconds=30)
    window.add(seg("Send the money today.", 0.0, 3.0))
    assert window.text(now=20.0) == "Send the money today."
    assert window.text(now=60.0) == ""


def test_empty_window_has_no_text():
    assert TranscriptWindow().text() == ""


# 2.3 has_enough_content() needs a minimum word count


def test_too_few_words_is_not_enough_to_judge():
    window = TranscriptWindow(min_words=6)
    window.add(seg("Hello? Yes, speaking.", 0.0, 2.0))  # 3 words
    assert window.has_enough_content() is False


def test_enough_words_across_segments_is_enough():
    window = TranscriptWindow(min_words=6)
    window.add(seg("Hi Nana, it's me.", 0.0, 1.5))  # 4 words
    window.add(seg("I'm in trouble.", 1.5, 3.0))  # 3 more
    assert window.has_enough_content() is True


def test_only_words_inside_the_window_count():
    window = TranscriptWindow(window_seconds=30, min_words=6)
    window.add(seg("This is a long friendly chat about the weather.", 0.0, 4.0))
    window.add(seg("Okay, bye.", 50.0, 51.0))
    assert window.has_enough_content() is False


def test_empty_window_is_not_enough():
    assert TranscriptWindow().has_enough_content() is False


def test_bad_settings_are_rejected():
    with pytest.raises(ValueError):
        TranscriptWindow(window_seconds=0)
    with pytest.raises(ValueError):
        TranscriptWindow(min_words=0)
