// WsClient: the browser's side of /ws/call. Sends audio as binary frames and
// control messages as JSON; hands every server message to onMessage.

// If this much audio is waiting to go out, the network can't keep up and the
// transcript would fall further and further behind; drop audio instead.
const MAX_BUFFERED_BYTES = 512 * 1024; // about 16 s of audio

export class WsClient {
  constructor(url, { onMessage, onClose }) {
    this.url = url;
    this.onMessage = onMessage;
    this.onClose = onClose;
    this.ws = null;
    this.droppedChunks = 0;
  }

  // Resolves when connected; rejects if the server can't be reached.
  connect() {
    return new Promise((resolve, reject) => {
      let opened = false;
      const ws = new WebSocket(this.url);
      ws.binaryType = "arraybuffer";
      ws.onopen = () => {
        opened = true;
        resolve();
      };
      ws.onmessage = (event) => {
        if (typeof event.data !== "string") return;
        let message;
        try {
          message = JSON.parse(event.data);
        } catch {
          console.warn("Ignoring a malformed message from the server");
          return;
        }
        this.onMessage(message);
      };
      ws.onclose = (event) => {
        if (!opened) reject(new Error("Can't reach the ScamShield server. Is it running?"));
        else this.onClose(event);
      };
      this.ws = ws;
    });
  }

  get isOpen() {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  sendAudio(buffer) {
    if (!this.isOpen) return;
    if (this.ws.bufferedAmount > MAX_BUFFERED_BYTES) {
      this.droppedChunks += 1;
      return;
    }
    this.ws.send(buffer);
  }

  sendControl(message) {
    if (this.isOpen) this.ws.send(JSON.stringify(message));
  }

  close() {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) this.ws.close();
  }
}

// The call socket. With a scenario id it plays that scripted demo call instead.
export function callSocketUrl(scenario) {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const query = scenario ? `?scenario=${encodeURIComponent(scenario)}` : "";
  return `${scheme}://${location.host}/ws/call${query}`;
}
