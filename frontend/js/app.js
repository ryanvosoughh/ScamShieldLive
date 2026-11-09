// Page controller: wires a call source (mic, audio file or scripted demo) to
// the WebSocket, the transcript and the risk meter, and turns every failure
// into a plain-language banner.
//
// One call at a time. Flow:
//   Start  -> source.prepare() (mic permission / decode file; nothing for a demo)
//          -> connect WebSocket -> server replies "ready" -> source.start()
//   During -> "transcript" messages fill the transcript; "state" messages move
//             the risk meter and highlight the evidence; "notice" messages put
//             up (or take down) a banner while the call carries on
//   Stop   -> stop audio, send {"type":"stop"} -> server flushes text, sends "ended"
//   A demo call also ends by itself when its script is over.

import { TARGET_RATE } from "./audio-format.js";
import { checkBrowser, supportMessage } from "./browser-support.js";
import { DemoSource } from "./demo-source.js";
import { ErrorBanner } from "./error-banner.js";
import { FileSource } from "./file-source.js";
import { MicCapture } from "./mic-capture.js";
import { RiskMeter } from "./risk-meter.js";
import { TranscriptView } from "./transcript-view.js";
import { WsClient, callSocketUrl } from "./ws-client.js";

const STOP_TIMEOUT_MS = 6000;
const LOST_CONNECTION = "Lost the connection to the server. Press Start to try again.";
const SERVER_DOWN = "Can't reach the ScamShield server. Start it with python run.py, then reload this page.";
const HINTS = {
  live: "Put the call on speaker near this computer. Audio is processed live and nothing is stored.",
  demo: "A pretend call plays and its words appear below, just like a real one. No microphone is used.",
};

const els = {
  start: document.getElementById("start-btn"),
  stop: document.getElementById("stop-btn"),
  fileBtn: document.getElementById("file-btn"),
  fileInput: document.getElementById("file-input"),
  demoBtn: document.getElementById("demo-btn"),
  scenario: document.getElementById("scenario"),
  modeLive: document.getElementById("mode-live"),
  modeDemo: document.getElementById("mode-demo"),
  modeNote: document.getElementById("mode-note"),
  liveControls: document.getElementById("live-controls"),
  demoControls: document.getElementById("demo-controls"),
  hint: document.getElementById("hint"),
  status: document.getElementById("status"),
  banner: document.getElementById("error-banner"),
  lag: document.getElementById("lag"),
};
const view = new TranscriptView(document.getElementById("transcript"));
const meter = new RiskMeter(document.getElementById("risk"));
const banner = new ErrorBanner(els.banner);
const support = checkBrowser();

let call = null; // the call in progress, or null
let demoCalls = []; // from /api/demo-calls
let liveAllowed = true; // false when the server runs in demo mode, or the browser can't capture any audio

els.start.addEventListener("click", () => startCall((handlers) => new MicCapture(handlers)));
els.fileBtn.addEventListener("click", () => els.fileInput.click());
els.fileInput.addEventListener("change", () => {
  const [file] = els.fileInput.files;
  els.fileInput.value = ""; // so picking the same file again still fires "change"
  if (file) startCall((handlers) => new FileSource(file, handlers));
});
els.demoBtn.addEventListener("click", () => {
  const chosen = demoCalls.find((demoCall) => demoCall.id === els.scenario.value);
  if (chosen) startCall(() => new DemoSource(chosen), { scenario: chosen.id });
});
els.modeLive.addEventListener("change", applyMode);
els.modeDemo.addEventListener("change", applyMode);
els.stop.addEventListener("click", () => stopCall());

init();

async function init() {
  const unsupported = supportMessage(support);
  if (unsupported) banner.show("browser", unsupported.text, { kind: unsupported.kind, page: true });
  if (!support.basics) {
    setBusy(true);
    els.stop.disabled = true;
    return;
  }
  const [health, calls] = await Promise.all([getJson("/health"), getJson("/api/demo-calls")]);
  if (!health) banner.show("server", SERVER_DOWN);
  demoCalls = Array.isArray(calls) ? calls : [];
  els.scenario.replaceChildren(
    ...demoCalls.map((demoCall) =>
      Object.assign(document.createElement("option"), {
        value: demoCall.id,
        textContent: `${demoCall.title} (${demoCall.seconds} s)`,
      }),
    ),
  );

  const notes = [];
  if (health?.mode === "demo") {
    liveAllowed = false;
    notes.push("This server is in demo mode, so live calls are switched off.");
  } else if (!support.mic && !support.file) {
    liveAllowed = false; // the banner says why
  } else if (health && !health.keys?.groq) {
    notes.push("No Groq key is set, so live calls are written out but not checked. Demo calls still work.");
  }
  if (!demoCalls.length) els.modeDemo.disabled = true;
  if (!liveAllowed) els.modeDemo.checked = true;
  els.modeNote.textContent = notes.join(" ");
  els.modeNote.hidden = notes.length === 0;
  applyMode();
}

async function getJson(url) {
  try {
    const response = await fetch(url);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function applyMode() {
  const demo = els.modeDemo.checked;
  els.liveControls.hidden = demo;
  els.demoControls.hidden = !demo;
  els.hint.textContent = demo ? HINTS.demo : HINTS.live;
  const placeholder = document.querySelector("#transcript .placeholder");
  if (placeholder) {
    placeholder.textContent = demo
      ? "Press Play demo call. The words will appear here."
      : "Press Start and speak. The words will appear here.";
  }
  setBusy(Boolean(call));
}

async function startCall(makeSource, { scenario = null } = {}) {
  if (call) return;
  const current = { ws: null, sentSamples: 0, worstLag: 0, error: null, stopRequested: false, finished: false };
  call = current;
  current.source = makeSource({
    onChunk: (buffer) => sendChunk(current, buffer),
    onEnded: () => stopCall(),
    onError: (message) => finish(current, message),
  });

  banner.clearCall();
  view.clear();
  meter.idle();
  els.lag.textContent = "";
  setBusy(true);
  setStatus("busy", "Getting ready…");

  try {
    await current.source.prepare();
    if (current.finished) return; // Stop was pressed while we waited
    setStatus("busy", "Connecting…");
    current.ws = new WsClient(callSocketUrl(scenario), {
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
      meter.listening({ analysis: message.analysis });
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
    case "state":
      meter.update(message);
      view.setEvidence(message.evidence || []);
      break;
    case "notice":
      // The call carries on; a notice with no message means the problem has gone.
      if (message.message) banner.show(message.code, message.message, { kind: "notice" });
      else banner.clear(message.code);
      break;
    case "error":
      // The server follows every error with "ended", which calls finish().
      current.error = message.message;
      banner.show("call", message.message);
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

  meter.callEnded();
  view.endCall();
  if (errorMessage) banner.show("call", errorMessage);
  setBusy(false);
  setStatus(errorMessage ? "error" : "idle", errorMessage ? "Stopped" : "Ready");
}

// How far the text trails the audio sent so far: audio clock now, minus the
// point in the audio the newest text reaches. A rough end-to-end figure.
// Demo calls send no audio, so nothing is shown for them.
function showLag(current, textEnd) {
  const lag = current.sentSamples / TARGET_RATE - textEnd;
  if (!Number.isFinite(lag) || lag < 0) return;
  current.worstLag = Math.max(current.worstLag, lag);
  els.lag.textContent = `Text delay ≈ ${lag.toFixed(1)} s (worst ${current.worstLag.toFixed(1)} s)`;
}

function setBusy(busy) {
  els.start.disabled = busy || !liveAllowed || !support.mic;
  els.fileBtn.disabled = busy || !liveAllowed || !support.file;
  els.demoBtn.disabled = busy || !demoCalls.length;
  els.scenario.disabled = busy;
  els.modeLive.disabled = busy || !liveAllowed;
  els.modeDemo.disabled = busy || !demoCalls.length;
  els.stop.disabled = !busy;
}

function setStatus(kind, text) {
  els.status.className = `status status--${kind}`;
  els.status.textContent = text;
}
