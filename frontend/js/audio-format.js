// The audio format the whole app agrees on: 16 kHz, mono, 16-bit PCM.
export const TARGET_RATE = 16000;
// 100 ms per chunk: small enough for low latency, large enough to keep
// WebSocket overhead low (10 messages a second).
export const CHUNK_SAMPLES = 1600;

// Float samples in [-1, 1] to 16-bit integers. (pcm-worklet.js has its own
// copy because audio worklets run in a separate scope.)
export function floatToInt16(floats) {
  const out = new Int16Array(floats.length);
  for (let i = 0; i < floats.length; i++) {
    const s = Math.max(-1, Math.min(1, floats[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}
