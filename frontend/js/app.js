// Page controller: wires an audio source (mic or file) to the WebSocket and
// the transcript view, and turns every failure into a plain-language banner.
//
// One call at a time. Flow:
//   Start -> source.prepare() (mic permission / decode file)
//         -> connect WebSocket -> server replies "ready" -> source.start()
//   Stop  -> stop audio, send {"type":"stop"} -> server flushes text, sends "ended"

import { TARGET_RATE } from "./audio-format.js";
import { FileSource } from "./file-source.js";
import { MicCapture } from "./mic-capture.js";
import { TranscriptView } from "./transcript-view.js";
import { WsClient, callSocketUrl } from "./ws-client.js";

const STOP_TIMEOUT_MS = 6000;
const LOST_CONNECTION = "Lost the connection to the server. Press Start to try again.";

const els = {
  start: document.getElementById("start-btn"),
  stop: document.getElementById("stop-btn"),
  fileBtn: document.getElementById("file-btn"),
  fileInput: document.getElementById("file-input"),
  status: document.getElementById("status"),
  banner: document.getElementById("error-banner"),
  lag: document.getElementById("lag"),
};
const view = new TranscriptView(document.getElementById("transcript"));

let call = null; // the call in progress, or null

els.start.addEventListener("click", () => startCall((handlers) => new MicCapture(handlers)));
els.fileBtn.addEventListener("click", () => els.fileInput.click());
els.fileInput.addEventListener("change", () => {
  const [file] = els.fileInput.files;
  els.fileInput.value = ""; // so picking the same file again still fires "change"
  if (file) startCall((handlers) => new FileSource(file, handlers));
});
els.stop.addEventListener("click", () => stopCall());

if (!("WebSocket" in window) || !("AudioContext" in window)) {
  showError("This browser is missing features ScamShield needs. Use a recent Chrome, Edge or Firefox.");
  els.start.disabled = true;
  els.fileBtn.disabled = true;
}

async function startCall(makeSource) {
  if (call) return;
  const current = { ws: null, sentSamples: 0, worstLag: 0, error: null, stopRequested: false, finished: false };
  call = current;
  current.source = makeSource({
    onChunk: (buffer) => sendChunk(current, buffer),
    onEnded: () => stopCall(),
    onError: (message) => finish(current, message),
  });

  hideError();
  view.clear();
  els.lag.textContent = "";
  setBusy(true);
  setStatus("busy", "Getting ready…");

  try {
    await current.source.prepare();
    if (current.finished) return; // Stop was pressed while we waited
    setStatus("busy", "Connecting…");
    current.ws = new WsClient(callSocketUrl(), {
      onMessage: (message) => onServerMessage(current, message),
      onClose: () => finish(current, current.stopRequested ? null : LOST_CONNECTION),
    });
    await current.ws.connect();
    if (current.finished) current.ws.close();
  } catch (err) {
    finish(current, err.message);
  }
}

function onServerMessage(current, message) {
  switch (message.type) {
    case "ready":
      current.source
        .start()
        .then(() => {
          if (!current.finished) setStatus("live", current.source.label);
        })
        .catch((err) => finish(current, err.message));
      break;
    case "transcript":
      view.update(message);
      if (message.text) showLag(current, message.end);
      break;
    case "error":
      // The server follows every error with "ended", which calls finish().
      current.error = message.message;
      showError(message.message);
      current.source.stop();
      break;
    case "ended":
      finish(current, current.error);
      break;
    default:
      console.warn("Unknown message from server:", message.type);
  }
}

function sendChunk(current, buffer) {
  if (!current.ws?.isOpen) return;
  current.ws.sendAudio(buffer);
  current.sentSamples += buffer.byteLength / 2; // 2 bytes per 16-bit sample
}

function stopCall() {
  const current = call;
  if (!current || current.stopRequested) return;
  current.stopRequested = true;
  current.source.stop();
  if (current.ws?.isOpen) {
    // Give the server a moment to send the last words, but don't hang forever.
    current.ws.sendControl({ type: "stop" });
    setStatus("busy", "Finishing…");
    current.stopTimer = setTimeout(() => finish(current), STOP_TIMEOUT_MS);
  } else {
    finish(current);
  }
}

function finish(current, errorMessage = null) {
  if (current.finished) return;
  current.finished = true;
  clearTimeout(current.stopTimer);
  current.source.stop();
  current.ws?.close();
  if (current.ws?.droppedChunks) {
    console.warn(`Dropped ${current.ws.droppedChunks} audio chunks: the connection was too slow.`);
  }
  if (call === current) call = null;

  if (errorMessage) showError(errorMessage);
  setBusy(false);
  setStatus(errorMessage ? "error" : "idle", errorMessage ? "Stopped" : "Ready");
}

// How far the text trails the audio sent so far: audio clock now, minus the
// point in the audio the newest text reaches. A rough end-to-end figure.
function showLag(current, textEnd) {
  const lag = current.sentSamples / TARGET_RATE - textEnd;
  if (!Number.isFinite(lag) || lag < 0) return;
  current.worstLag = Math.max(current.worstLag, lag);
  els.lag.textContent = `Text delay ≈ ${lag.toFixed(1)} s (worst ${current.worstLag.toFixed(1)} s)`;
}

function setBusy(busy) {
  els.start.disabled = busy;
  els.fileBtn.disabled = busy;
  els.stop.disabled = !busy;
}

function setStatus(kind, text) {
  els.status.className = `status status--${kind}`;
  els.status.textContent = text;
}

function showError(message) {
  els.banner.textContent = message;
  els.banner.hidden = false;
}

function hideError() {
  els.banner.hidden = true;
  els.banner.textContent = "";
}
