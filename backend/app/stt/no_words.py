"""Spot a call the transcriber can hear but can't understand, most likely not English.

Deepgram's English model doesn't guess at speech in another language: it
returns nothing. Measured on French, Spanish and German clips: each burst of
speech it detected (a SpeechStarted event) ended in a final with no words.
On English clips, every burst ended in a final with words. Very faint or
muffled English does the same thing as another language, so the notice covers both.

Counted per burst of speech, not per empty final: Deepgram also sends empty
finals in silence (both English clips ended with one after the last sentence),
and a quiet stretch must not look like a foreign call.
Words from any burst reset the count, so a cough between English sentences
never adds up.
"""
from __future__ import annotations

NO_WORDS_CODE = "no_words"
NO_WORDS_MESSAGE = (
    "Speech is coming through, but no words are being recognised. ScamShield only understands "
    "English for now, so it can't check a call in another language. If this call is in English, "
    "move the phone closer to the computer."
)
DEFAULT_WORDLESS_BURSTS = 3


class SpeechWithoutWords:
    def __init__(self, bursts: int = DEFAULT_WORDLESS_BURSTS) -> None:
        if bursts < 1:
            raise ValueError("bursts must be at least 1")
        self.bursts = bursts
        self.showing = False
        self._in_speech = False  # speech has started and no final has closed it yet
        self._wordless = 0  # bursts in a row that ended with no words

    def speech_started(self) -> None:
        self._in_speech = True

    def final(self, text: str) -> bool | None:
        """Feed every final result. True: show the notice. False: clear it. None: no change."""
        if text:
            self._in_speech = False
            self._wordless = 0
            if self.showing:
                self.showing = False
                return False
            return None
        if not self._in_speech:
            return None  # an empty final in silence
        self._in_speech = False
        self._wordless += 1
        if self._wordless >= self.bursts and not self.showing:
            self.showing = True
            return True
        return None
