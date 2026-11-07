// TranscriptView: live text. Settled (final) text is shown normally; the
// engine's running guess for the current phrase (interim) is shown in grey
// and replaced as it changes. Phase 2 adds highlighting of evidence phrases.
//
// All text goes in through textContent, never innerHTML: the transcript is
// whatever a caller said, so it is treated as untrusted.

// A pause longer than this starts a new line, so turns read more naturally.
const NEW_LINE_GAP_SECONDS = 1.5;

export class TranscriptView {
  constructor(element) {
    this.el = element;
    this.placeholder = element.querySelector(".placeholder");
  }

  clear() {
    this.el.replaceChildren();
    this.line = null;
    this.lastEnd = null;
    this.interim = document.createElement("span");
    this.interim.className = "interim";
    this.newLine();
  }

  showPlaceholder() {
    if (this.placeholder) this.el.replaceChildren(this.placeholder);
  }

  update({ text, is_final: isFinal, start, end }) {
    const stickToBottom = this.el.scrollHeight - this.el.scrollTop - this.el.clientHeight < 40;

    if (isFinal) {
      this.interim.textContent = "";
      if (text) {
        if (this.lastEnd !== null && start - this.lastEnd > NEW_LINE_GAP_SECONDS) this.newLine();
        const span = document.createElement("span");
        span.className = "final";
        span.textContent = text + " ";
        this.line.insertBefore(span, this.interim);
        this.lastEnd = end;
      }
    } else {
      this.interim.textContent = text;
    }

    if (stickToBottom) this.el.scrollTop = this.el.scrollHeight;
  }

  newLine() {
    this.line = document.createElement("p");
    this.line.className = "line";
    this.line.append(this.interim);
    this.el.append(this.line);
  }
}
