// Evidence highlighting. The scam check only quotes phrases it found in the
// transcript, matching them while ignoring case, punctuation and curly quotes
// (see normalised_words in analyzer.py). The same rule is used here, so a
// phrase like "dont tell mom" still marks "Don't tell Mom," on screen.
//
// Text is always inserted as text nodes, never as HTML: the transcript is
// whatever the caller said.

const NOT_WORD = "[^a-z0-9'‘’]";

// A pattern that finds the phrase as whole words, or null if it has no words.
export function phrasePattern(phrase) {
  const words = phrase.toLowerCase().replace(/[‘’]/g, "'").match(/[a-z0-9']+/g);
  if (!words) return null;
  // Words only hold letters, digits and apostrophes, so nothing else needs escaping.
  const body = words.map((word) => word.replace(/'/g, "['‘’]")).join(`${NOT_WORD}+`);
  return new RegExp(`(?<![a-z0-9'‘’])${body}(?![a-z0-9'‘’])`, "gi");
}

// The [start, end) ranges of text covered by any pattern, sorted and merged.
export function findRanges(text, patterns) {
  const ranges = [];
  for (const pattern of patterns) {
    pattern.lastIndex = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      ranges.push([match.index, match.index + match[0].length]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const [start, end] of ranges) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

// Fill `element` with `text`, wrapping the matched ranges in <mark>.
export function renderHighlighted(element, text, patterns) {
  const nodes = [];
  let position = 0;
  for (const [start, end] of findRanges(text, patterns)) {
    if (start > position) nodes.push(document.createTextNode(text.slice(position, start)));
    const mark = document.createElement("mark");
    mark.textContent = text.slice(start, end);
    nodes.push(mark);
    position = end;
  }
  if (position < text.length) nodes.push(document.createTextNode(text.slice(position)));
  element.replaceChildren(...nodes);
}
