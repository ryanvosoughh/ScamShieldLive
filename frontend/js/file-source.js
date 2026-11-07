// FileSource: the recorded-audio fallback. Plays an audio file out loud and
// streams it to the server at real-time speed, exactly as if it came from the
// microphone. Same interface as MicCapture, so the rest of the page doesn't care.
//
// Useful when browser mic streaming is flaky, and for repeatable tests.

import { CHUNK_SAMPLES, TARGET_RATE, floatToInt16 } from "./audio-format.js";

const MAX_SECONDS = 15 * 60;

export class FileSource {
  constructor(file, { onChunk, onEnded, onError }) {
    this.file = file;
    this.onChunk = onChunk;
    this.onEnded = onEnded;
    this.onError = onError;
    this.timer = null;
  }

  get label() {
    return `Playing ${this.file.name}`;
  }

  async prepare() {
    this.context = new AudioContext();
    try {
      this.decoded = await this.context.decodeAudioData(await this.file.arrayBuffer());
    } catch {
      this.stop();
      throw new Error("Couldn't read that audio file. Try a WAV or MP3.");
    }
    if (this.decoded.duration > MAX_SECONDS) {
      this.stop();
      throw new Error("That file is longer than 15 minutes. Use a shorter clip.");
    }
    this.samples = await resampleToTarget(this.decoded);
  }

  async start() {
    if (this.context.state === "suspended") await this.context.resume();
    this.player = this.context.createBufferSource();
    this.player.buffer = this.decoded;
    this.player.connect(this.context.destination);
    this.player.start();

    this.startedAt = performance.now();
    this.sent = 0;
    // Send whatever is due by the clock rather than a fixed amount per tick, so
    // the stream stays in real time even if timers fire late (background tabs).
    this.timer = setInterval(() => this.pump(), 100);
  }

  pump() {
    const elapsed = (performance.now() - this.startedAt) / 1000;
    const due = Math.min(this.samples.length, Math.floor(elapsed * TARGET_RATE));
    while (this.sent < due) {
      const end = Math.min(due, this.sent + CHUNK_SAMPLES);
      this.onChunk(floatToInt16(this.samples.subarray(this.sent, end)).buffer);
      this.sent = end;
    }
    if (this.sent >= this.samples.length) {
      this.stop();
      this.onEnded();
    }
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    try {
      this.player?.stop();
    } catch {
      /* already stopped */
    }
    if (this.context && this.context.state !== "closed") this.context.close();
  }
}

// Let the browser's own resampler convert to 16 kHz mono: an offline audio
// context renders the file at the target rate and mixes channels down.
async function resampleToTarget(buffer) {
  const length = Math.ceil(buffer.duration * TARGET_RATE);
  const offline = new OfflineAudioContext(1, length, TARGET_RATE);
  const source = offline.createBufferSource();
  source.buffer = buffer;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return rendered.getChannelData(0);
}
