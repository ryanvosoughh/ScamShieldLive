#!/usr/bin/env bash
# Makes two short test calls with macOS text-to-speech, for the
# "Use an audio file instead" fallback. Output goes to samples/ (git-ignored).
#
#   bash scripts/make_sample_audio.sh
#
# Not on a Mac? Record any short WAV or MP3 of yourself reading a script.
set -euo pipefail

if ! command -v say >/dev/null || ! command -v afconvert >/dev/null; then
  echo "This script needs macOS 'say' and 'afconvert'. Record your own WAV/MP3 instead." >&2
  exit 1
fi

cd "$(dirname "$0")/.."
mkdir -p samples

make_clip() {
  local name="$1" text="$2"
  say -o "samples/$name.aiff" "$text"
  # 16 kHz mono 16-bit WAV: the same format the app streams.
  afconvert -f WAVE -d LEI16@16000 -c 1 "samples/$name.aiff" "samples/$name.wav"
  rm "samples/$name.aiff"
  echo "Wrote samples/$name.wav"
}

make_clip grandchild_scam "Hi Nana, it's me. I'm in real trouble and I need your help right now. \
I was in a car accident and the police say I have to pay bail today. Please don't tell Mum, she'll be so angry. \
Can you go to the shop, buy some gift cards, and read me the numbers on the back?"

make_clip normal_call "Hi Gran, it's Sam. Just ringing to say thanks for the birthday card. \
We're still on for Sunday lunch, aren't we? I'll pick you up at twelve. Love you, see you then."
