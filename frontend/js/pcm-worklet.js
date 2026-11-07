// Runs on the browser's audio thread. Turns microphone audio (usually 44.1 or
// 48 kHz float samples) into 16 kHz 16-bit PCM, the format Deepgram expects,
// and posts it to the page in ~100 ms chunks.

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { targetRate, chunkSamples } = options.processorOptions;
    // `sampleRate` is a global in the audio worklet scope: the input rate.
    this.ratio = sampleRate / targetRate; // e.g. 48000 / 16000 = 3 input samples per output
    this.chunkSamples = chunkSamples;
    this.chunk = new Int16Array(chunkSamples);
    this.filled = 0;
    // Downsampling by averaging: each output sample is the mean of the input
    // samples it covers. Averaging is a crude low-pass filter, which stops
    // high frequencies folding back in as noise. Works for non-integer ratios too.
    this.sum = 0;
    this.count = 0;
    this.phase = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]; // first input, first channel (mono)
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i];
      this.count += 1;
      this.phase += 1;
      if (this.phase >= this.ratio) {
        this.phase -= this.ratio;
        this.push(this.sum / this.count);
        this.sum = 0;
        this.count = 0;
      }
    }
    return true; // keep the processor alive
  }

  push(sample) {
    const s = Math.max(-1, Math.min(1, sample));
    this.chunk[this.filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    if (this.filled === this.chunk.length) {
      // Transfer the buffer (no copy) and start a fresh one. Transferring
      // detaches the old array (its length becomes 0), so size the new one
      // from the saved chunk size, not from this.chunk.length.
      this.port.postMessage(this.chunk.buffer, [this.chunk.buffer]);
      this.chunk = new Int16Array(this.chunkSamples);
      this.filled = 0;
    }
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
