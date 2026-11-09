// What this browser can do, checked once when the page loads, so the page can
// say up front what won't work instead of failing when Start is pressed.
// Takes the window as an argument so it can be tried with a pretend one.
//
// (Browsers too old to run this file at all get the <script nomodule> message
// in index.html instead.)

export function checkBrowser(win = window) {
  const audio = "AudioContext" in win;
  return {
    basics: "WebSocket" in win && "fetch" in win,
    // The microphone and AudioWorklet only work on https or localhost.
    secure: Boolean(win.isSecureContext),
    mic: Boolean(win.navigator?.mediaDevices?.getUserMedia) && "AudioWorkletNode" in win && audio,
    file: audio && "OfflineAudioContext" in win,
  };
}

// The banner message for what's missing, or null when everything works.
export function supportMessage(support) {
  if (!support.basics) {
    return { kind: "error", text: "This browser is too old for ScamShield. Use a recent Chrome, Edge or Firefox." };
  }
  if (support.mic) return null;
  if (!support.secure) {
    return {
      kind: "notice",
      text: "The microphone only works when this page is opened at http://localhost on the computer running ScamShield. An audio file or a demo call still works.",
    };
  }
  if (support.file) {
    return {
      kind: "notice",
      text: "This browser can't stream the microphone, so live listening is off. Use a recent Chrome, Edge or Firefox, or try an audio file or a demo call.",
    };
  }
  return {
    kind: "notice",
    text: "This browser can't capture audio, so only demo calls work here. Use a recent Chrome, Edge or Firefox for live calls.",
  };
}
