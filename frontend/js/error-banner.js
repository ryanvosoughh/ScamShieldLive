// ErrorBanner: the strip above the risk meter that says what has gone wrong, in plain words.
//
// Two kinds of message:
//   error   something stopped the call or the page (mic blocked, server not running)
//   notice  a problem the call carries on through (the scam check isn't answering,
//           no words are recognised). Calmer colours, and the call keeps going.
//
// Every message has a code. A new message with the same code replaces the old
// one instead of piling up, and the server can take a notice down by its code.
// Page messages (an unsupported browser) stay until the page reloads; the rest
// are cleared when the next call starts.

export class ErrorBanner {
  constructor(root) {
    this.root = root;
    this.messages = new Map(); // code -> { text, kind, page }
  }

  show(code, text, { kind = "error", page = false } = {}) {
    this.messages.set(code, { text, kind, page });
    this.render();
  }

  clear(code) {
    if (this.messages.delete(code)) this.render();
  }

  // A new call starts clean, apart from problems with the page itself.
  clearCall() {
    for (const [code, message] of this.messages) {
      if (!message.page) this.messages.delete(code);
    }
    this.render();
  }

  render() {
    const messages = [...this.messages.values()];
    this.root.replaceChildren(
      ...messages.map(({ text, kind }) =>
        Object.assign(document.createElement("p"), { className: `banner__item banner__item--${kind}`, textContent: text }),
      ),
    );
    this.root.hidden = messages.length === 0;
    this.root.classList.toggle("banner--notice", messages.length > 0 && messages.every((m) => m.kind === "notice"));
  }
}
