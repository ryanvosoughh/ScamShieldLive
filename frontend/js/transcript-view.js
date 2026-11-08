// TranscriptView: live text. Settled (final) text is shown normally; the
// engine's running guess for the current phrase (interim) is shown in grey
// and replaced as it changes. Evidence phrases from the scam check are
// highlighted in the settled text.
//
// All text goes in through text nodes, never innerHTML: the transcript is
// whatever a caller said, so it is treated as untrusted.

import { phrasePattern, renderHighlighted } from "./highlight.js";

// A pause longer than this starts a new line, so turns read more naturally.
const NEW_LINE_GAP_SECONDS = 1.5;

export class TranscriptView {
  constructor(element) {
    this.el = element;
    this.placeholder = element.querySelector(".placeholder");
    this.finals = []; // { span, text } for every settled phrase
    this.patterns = [];
    this.evidenceKey = "";
  }

  clear() {
    this.el.replaceChildren();
    this.finals = [];
    this.patterns = [];
    this.evidenceKey = "";
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
        renderHighlighted(span, `${text} `, this.patterns);
        this.line.insertBefore(span, this.interim);
        this.finals.push({ span, text });
        this.lastEnd = end;
      }
    } else {
      this.interim.textContent = text;
    }

    if (stickToBottom) this.el.scrollTop = this.el.scrollHeight;
  }

  // The call is over: drop any half-heard grey text, which will never be settled now.
  endCall() {
    if (this.interim) this.interim.textContent = "";
  }

  // Highlight these phrases wherever they appear in the settled text.
  setEvidence(phrases) {
    const key = phrases.join("\n");
    if (key === this.evidenceKey) return; // nothing new to mark
    this.evidenceKey = key;
    this.patterns = phrases.map(phrasePattern).filter(Boolean);
    for (const { span, text } of this.finals) renderHighlighted(span, `${text} `, this.patterns);
  }

  newLine() {
    this.line = document.createElement("p");
    this.line.className = "line";
    this.line.append(this.interim);
    this.el.append(this.line);
  }
}
