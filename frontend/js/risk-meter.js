// RiskMeter: the card at the top of the page that says how risky the call is.
//
// Plain words first, colour second: every level has its own wording, so the
// meaning never depends on colour alone. The title is the server's "headline"
// (alerts/wording.py), so the screen and the spoken warning use the same words.
// The reason and "what to do" only show for a warning (yellow or red): a green
// meter with a worrying sentence next to it would be confusing.

// The red flags the scam check can report (RED_FLAGS in prompts.py), in plain words.
const RED_FLAG_WORDS = {
  asks_for_code: "Asked for a code, PIN or password",
  unusual_payment: "Wants gift cards, crypto, a wire transfer or a courier",
  safe_account: "Wants money moved to a “safe account”",
  remote_control: "Wants control of your computer",
  money_for_stranger: "Money for someone you've never met",
};

export class RiskMeter {
  constructor(root) {
    this.root = root;
    this.part = (name) => root.querySelector(`[data-part="${name}"]`);
    this.level = "unknown";
    this.idle();
  }

  // Before any call.
  idle() {
    this.show("unknown", {
      title: "Not listening",
      reason: "Start a call and this will show whether it sounds like a scam.",
    });
  }

  // The call has connected; no check has run yet.
  listening({ analysis }) {
    this.show("unknown", analysis
      ? { title: "Listening…", reason: "The first check runs once a few words have been said." }
      : { title: "Scam check is off", reason: "No Groq key is set on the server, so this call is only written out." });
  }

  // A "state" message from the server.
  update(state) {
    const warning = state.level === "yellow" || state.level === "red";
    const notes = [];
    if (state.stale && state.level !== "unknown") {
      notes.push("The latest check didn't answer, so this is the last result.");
    }

    if (state.level === "unknown") {
      this.show("unknown", {
        title: state.headline,
        reason: "The scam check didn't answer. It will try again with the next words.",
        notes,
        breakdown: state.breakdown,
      });
      return;
    }
    this.show(state.level, {
      title: state.headline,
      reason: warning ? state.reason : "Nothing worrying has been said.",
      action: warning ? state.next_action : "",
      flags: warning ? state.red_flags.map((flag) => RED_FLAG_WORDS[flag] || flag) : [],
      score: state.score,
      notes,
      breakdown: state.breakdown,
    });
  }

  // The call is over: keep the last result on screen, or go back to idle if there was none.
  callEnded() {
    if (this.level === "unknown") {
      this.idle();
      return;
    }
    const note = this.part("note");
    note.textContent = [note.textContent, "The call has ended. This was the last result."].filter(Boolean).join(" ");
    note.hidden = false;
  }

  show(level, { title, reason = "", action = "", flags = [], score = null, notes = [], breakdown = [] }) {
    this.level = level;
    this.root.className = `risk risk--${level}`;
    this.part("title").textContent = title;
    this.part("reason").textContent = reason;
    this.part("reason").hidden = !reason;

    this.part("action-text").textContent = action;
    this.part("action").hidden = !action;

    this.part("flags").replaceChildren(
      ...flags.map((words) => Object.assign(document.createElement("li"), { textContent: words })),
    );
    this.part("flags").hidden = flags.length === 0;

    const hasScore = typeof score === "number";
    this.part("score").textContent = hasScore ? `Risk ${Math.round(score)}/100` : "";
    this.part("fill").style.width = hasScore ? `${Math.max(0, Math.min(100, score))}%` : "0";

    this.part("note").textContent = notes.join(" ");
    this.part("note").hidden = notes.length === 0;

    this.part("breakdown").replaceChildren(
      ...breakdown.map((line) => Object.assign(document.createElement("li"), { textContent: line })),
    );
    this.part("details").hidden = breakdown.length === 0;
  }
}
