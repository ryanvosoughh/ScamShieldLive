// ErrorBanner: the strip above the risk meter that says what has gone wrong, in
// plain words (mic blocked, server not running, connection lost). One message
// at a time: a new one replaces the old, and the next call starts with it hidden.

export class ErrorBanner {
  constructor(root) {
    this.root = root;
  }

  show(text) {
    this.root.textContent = text;
    this.root.hidden = false;
  }

  hide() {
    this.root.textContent = "";
    this.root.hidden = true;
  }
}
