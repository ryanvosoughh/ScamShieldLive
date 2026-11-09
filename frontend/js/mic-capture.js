// MicCapture: asks for the microphone and emits 16 kHz PCM chunks.
//
// Two steps on purpose: prepare() asks for permission and builds the audio
// graph; start() begins emitting. The page calls start() only once the server
// says transcription is ready, so no audio is lost or queued.

import { CHUNK_SAMPLES, TARGET_RATE } from "./audio-format.js";

export class MicCapture {
  constructor({ onChunk, onError }) {
    this.onChunk = onChunk;
    this.onError = onError;
    this.running = false;
  }

  get label() {
    return "Listening";
  }

  async prepare() {
    if (!window.isSecureContext) {
      throw new Error("The microphone only works on a secure page. Open the app at http://localhost:8000.");
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      throw new Error(
        "This browser can't stream the microphone. Use a recent Chrome, Edge or Firefox, or use an audio file instead.",
      );
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          // Echo cancellation will matter in Phase 3, when the app speaks alerts out loud.
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      throw new Error(describeMicError(err));
    }

    this.context = new AudioContext();
    if (this.context.sampleRate < TARGET_RATE) {
      this.stop();
      throw new Error("Your audio device runs below 16 kHz, which is too low for transcription.");
    }
    await this.context.audioWorklet.addModule(new URL("./pcm-worklet.js", import.meta.url));
    this.source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "pcm-capture", {
      processorOptions: { targetRate: TARGET_RATE, chunkSamples: CHUNK_SAMPLES },
    });
    this.node.port.onmessage = (event) => {
      if (this.running) this.onChunk(event.data);
    };

    const [track] = this.stream.getAudioTracks();
    track.addEventListener("ended", () => {
      if (this.running) this.onError("The microphone was disconnected.");
    });
  }

  async start() {
    this.source.connect(this.node);
    // The worklet writes no output (silence), but it must be connected to the
    // destination or some browsers never run it.
    this.node.connect(this.context.destination);
    if (this.context.state === "suspended") await this.context.resume();
    this.running = true;
  }

  stop() {
    this.running = false;
    this.source?.disconnect();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop()); // turns off the mic indicator
    if (this.context && this.context.state !== "closed") this.context.close();
  }
}

function describeMicError(err) {
  switch (err?.name) {
    case "NotAllowedError":
    case "SecurityError":
      // Chrome says "Permission denied by system" when the computer, not the page, is blocking it.
      if (/system/i.test(err.message || "")) {
        return "Your computer is stopping the browser from using the microphone. On a Mac, open System Settings, then Privacy & Security, then Microphone, and turn your browser on. Then press Start listening again.";
      }
      return "Microphone access is blocked for this page. Click the icon at the left of the address bar, allow the microphone, then press Start listening again. An audio file or a demo call works without it.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No microphone was found. Plug one in, or use an audio file instead.";
    case "NotReadableError":
    case "AbortError":
      return "The microphone is busy in another app. Close that app and try again.";
    default:
      return `Couldn't start the microphone (${err?.message || "unknown error"}).`;
  }
}
