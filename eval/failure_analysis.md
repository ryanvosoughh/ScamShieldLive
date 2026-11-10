# Failure analysis

Why each mistake in the evaluation happened, and what would fix it. The numbers are in `results.md`;
how the cases were made is in `README.md`.

This file is written by hand, unlike `results.md`, so it describes these two runs and needs updating
if they are run again:

| Run | When (UTC) | Prompt | Code |
|---|---|---|---|
| 24 test cases (`results.json`) | 10 Nov 2026, 13:59 | `0e65300ae02f` | `a1ec0c1` |
| Demo-call timing (`timing.json`) | 10 Nov 2026, 14:50 | `0e65300ae02f` | `1ab4130` |



## Summary

| What | Kind | Fix | Decision |
|---|---|---|---|
| `n06_grandson_fixes_laptop` | False alarm | A signal outside the words: is the caller a saved contact? | Keep the label, accept the false alarm |
| `s04_bank_safe_account_polite` | Near miss | Already handled: the red-flag rule in the scorer | No change; add more polite cases |
| Demo calls with a Groq key | Late or missing warnings | Spread the checks through the call | Kept the 4 s pacing for now; a known limit |

No scam in the 24 cases was missed.

## 1. False alarm: the grandson fixing a laptop (`n06`)

**What happened.** A grandson the person had texted for help says he'll connect to her laptop
"like last time" and asks her to read out the number the app shows. The meter went red: model
risk 75, red flags `asks_for_code` and `remote_control`. The model's reason: *"They want you to give
them a code and control your computer, which is a common scam."*

**Why.** The words are the same as a tech-support scam's: open an app, read out a number, let me see
your screen. The only differences are who is really calling and who asked for the help ("you texted
me"), and a scammer can claim both. The prompt's look-alike list says a relative helping with a
computer is normal, but nothing in the text proves that this caller is that relative, so the model
took the cautious reading.

**What would fix it.** Not the prompt. Telling it to trust "you asked me to" would let through real
remote-access scams, such as `s05`, which ask for the same number. The fix needs a signal from
outside the words:

- whether the number calling is a saved contact, or what its caller-ID reputation is. A phone app
  has this; text from a call does not;
- or a quick question to the person ("did you ask for this help?"). That is the safe-word challenge
  in the plan, which I left out to keep the project small.

**Decision.** Keep the label as normal and count it as a false alarm. Warning here is the safer
mistake: the advice shown is to hang up and call back on a number you already know, which a real
grandson would understand.

## 2. Near miss: the polite safe-account call (`s04`)

**What happened.** A calm "security team" asks to move savings to a "safe account", with "take your
time, there's no pressure". The model gave a risk of only 55, which is yellow on its own (40 to 69).
It reported the `safe_account` red flag, and the scorer turned that into red.

**Why.** The model scores calm, polite calls lower even when the request is clearly a scam. The
prompt already says a pleasant tone doesn't make a request safe; the model spots the request (it
names the red flag) but still puts a lower number on it.

**What would fix it.** It is already fixed by design: any red flag makes the meter red, whatever the
number, so a polite tone can't talk the score down. Two cautions:

- the red-flag list is the safety net. A polite scam whose request isn't on the list would only get
  as far as the model's number; here that is still yellow, so a warning, but a softer one;
- the set has only four polite scams. More would show how often the number dips like this.

**Decision.** No change to the code or the prompt.

## 3. Late warnings on the demo calls (the check pacing)

**What happened.** Played in real time with the real check on Groq, the three demo calls gave:

| Call | Checks at | The ask is said at | Call ends | Result |
|---|---|---|---|---|
| Fake bank fraud team | 5.8, 10.0, 15.5, 19.5, 25.0 s | 32.9 s | 50.3 s | Never warned |
| Grandchild in trouble | 4.9, 11.0, 20.2, 24.0, 29.7 s | 34.0 s | 45.8 s | Yellow at 29.7 s, never red |
| Grandchild saying thank you | 4.8 to 23.1 s | – | 30.1 s | Stayed green (correct) |

**Why.** Groq's free tier allows about 8,000 tokens a minute and one check is about 1,350, so the
app allows checks every 4 s but at most 5 a minute. All 5 were used up on the small talk in the first
25 to 30 seconds, and the next check wasn't allowed until a minute had passed. Both scam calls ended
before then, so the request itself, the part that turns the meter red, was never checked. Scams
usually build up first and ask later, so this is the worst moment to stop checking.

The 24 test cases couldn't show this, because each one is a single check on a short call. Without a
Groq key the demo calls use scripted verdicts, which have no cap, so the keyless demo isn't affected.

**What would fix it.**

| Option | Effect | Cost |
|---|---|---|
| One check every 12 s, no cap | Checks spread through the call; red an estimated 7 to 12 s after the ask (not yet measured) | The first warning can come up to 12 s later |
| A paid Groq tier, with `CHECKS_PER_MINUTE=15` in `.env` | Checks every 4 s all through the call; a settings change only | Money |
| Smaller checks (a shorter prompt or window) | More checks fit in a minute | Accuracy would need measuring again |
| Widen the gap as checks are used | An earlier first warning than one every 12 s | More code |

**Decision.** I kept the 4 s pacing for now. The effect: on Groq's free tier, a call that is still
going after its first 5 checks isn't checked again until a minute has passed, so a scam asked for in
that gap is warned about late, not at the moment it is asked. In a longer call the warning still
comes once the minute is up (an earlier live test turned red at 70 s), and a failed or missing check
is never shown as safe.

## How far to trust these numbers

- **A smoke test, n = 24.** 12 of 12 scams caught is consistent with a true catch rate anywhere from
  about 76% to 100%, and 1 false alarm in 12 with anything from about 1.5% to 35% (95% Wilson
  intervals). One more case either way moves a rate by about 8 points.
- **One writer.** All 24 cases were drafted by Claude, so they are tidier and more alike than real
  calls.
- **Text only.** Phone audio, accents, noise and speech-recognition mistakes (beyond two cases) were
  not tested by the 24 cases.
- **Look-alikes on purpose.** 10 of the 12 normal calls were chosen to be hard, so the false-alarm
  rate is likely worse than on everyday calls.
