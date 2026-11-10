// SpeechAlert: says a warning out loud with the browser's own voice (speechSynthesis).
//
// The server decides what to say and when (AlertPolicy); this only speaks it.
// While it speaks, the microphone must not listen: the app would transcribe
// its own warning, and the next check would read "this sounds like a scam" as
// part of the call. So it calls onStart before the first word and onEnd once
// it has finished, plus a short pause for the room's echo to die down.
// A new warning cuts off the one before it: it is always the louder one.

const ECHO_TAIL_MS = 400;
const SPEAKING_RATE = 0.95; // a little slower than default, for older listeners

export class SpeechAlert {
  constructor({ onStart = () => {}, onEnd = () => {} } = {}) {
    this.onStart = onStart;
    this.onEnd = onEnd;
    this.synth = "speechSynthesis" in window ? window.speechSynthesis : null;
    this.supported = Boolean(this.synth) && "SpeechSynthesisUtterance" in window;
    this.active = false; // from onStart until onEnd: the mic is paused
    this.current = null; // the utterance being spoken
    this.tailTimer = null;
    this.watchdog = null;
  }

  say(text) {
    if (!this.supported || !text) return;
    clearTimeout(this.tailTimer);
    if (!this.active) {
      this.active = true;
      this.onStart();
    }
    this.current = null; // so the one being cut off doesn't count as finishing
    this.synth.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = document.documentElement.lang || "en";
    utterance.rate = SPEAKING_RATE;
    const finished = () => {
      if (this.current !== utterance) return;
      this.current = null;
      clearTimeout(this.watchdog);
      this.tailTimer = setTimeout(() => this.finish(), ECHO_TAIL_MS);
    };
    utterance.onend = finished;
    utterance.onerror = finished;
    this.current = utterance;
    this.synth.speak(utterance);

    // Browsers sometimes never fire "end". The mic must never stay paused for
    // good, or the call would quietly stop being checked.
    clearTimeout(this.watchdog);
    this.watchdog = setTimeout(() => {
      this.synth.cancel();
      finished();
    }, 3000 + text.length * 120);
  }

  // Stop talking now (the person pressed Stop, or a new call is starting).
  cancel() {
    this.current = null;
    clearTimeout(this.watchdog);
    clearTimeout(this.tailTimer);
    if (this.synth) this.synth.cancel();
    this.finish();
  }

  finish() {
    if (!this.active) return;
    this.active = false;
    this.onEnd();
  }
}
