# Failure analysis

Why each mistake in the evaluation happened, and what would fix it. The numbers are in `results.md`;
how the cases were made is in `README.md`.

This file is written by hand, unlike `results.md`, so it describes these runs and needs updating
if they are run again:

| Run | When (UTC) | Prompt | Code |
|---|---|---|---|
| 29 test cases (`results.json`) | 10 Nov 2026, 21:36 | `0e65300ae02f` | `01103fd` |
| Demo-call timing before the pacing fix (`timing_baseline.json`) | 10 Nov 2026, 14:50 | `0e65300ae02f` | `1ab4130` |
| Demo-call timing after the pacing fix (`timing.json`) | 10 Nov 2026, 21:01 | `0e65300ae02f` | `ce6b9d0` plus the fix, before it was committed |



## Summary

| What | Kind | Fix | Decision |
|---|---|---|---|
| `n06_grandson_fixes_laptop` | False alarm | A signal outside the words: is the caller a saved contact? | Keep the label, accept the false alarm |
| `s04_bank_safe_account_polite` | Near miss | Already handled: the red-flag rule in the scorer | No change; add more polite cases |
| `s13_rebate_identity_details` | **Missed** | Make identity details a warning sign: a red flag, or a rule in the risk scale | Not fixed yet; a known limit |
| `s16_pension_review_polite`, `s17_loyalty_discount_card_number` | Near misses | The model stretched a red flag to fit; the definitions need widening on purpose | Not changed yet |
| Demo calls with a Groq key | Late or missing warnings | Spread the checks through the call | **Fixed:** one check every 12 s; red 7 to 9 s after the ask |

One scam in 17 was missed: `s13`. The first 24 cases gave the same results as before the five new scams were added.

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

## 3. Late warnings on the demo calls (the check pacing): fixed

**What happened.** Played in real time with the real check on Groq, the three demo calls first gave:

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

The single-check test cases couldn't show this, because each one is a single check on a short call. Without a
Groq key the demo calls use scripted verdicts, which have no cap, so the keyless demo isn't affected.

**What would fix it.** I compared four options:

| Option | Effect | Cost |
|---|---|---|
| **One check every 12 s, no cap (chosen)** | Checks spread through the call; red an estimated 7 to 12 s after the ask | The first warning can come up to 12 s later |
| A paid Groq tier, with `CHECKS_PER_MINUTE=15` in `.env` | Checks every 4 s all through the call; a settings change only | Money |
| Smaller checks (a shorter prompt or window) | More checks fit in a minute | Accuracy would need measuring again |
| Widen the gap as checks are used | An earlier first warning than one every 12 s | More code |

**Decision.** I chose one check every 12 s. It uses the same budget (5 checks a minute), spread
evenly, and it made the code simpler: the per-minute counter and the `CHECKS_PER_MINUTE` setting are
gone. Keyless demos still check every 4 s, because scripted verdicts cost nothing.

**After the fix.** The same three calls, played again the same way:

| Call | Checks at | The ask is said at | Result |
|---|---|---|---|
| Fake bank fraud team | 5.8, 17.5, 29.9, 41.8 s | 32.9 s | **Red at 41.8 s**, 8.9 s after the ask |
| Grandchild in trouble | 5.6, 16.8, 29.5, 41.3 s | 34.0 s | Yellow at 29.5 s, **red at 41.3 s**, 7.3 s after the ask |
| Grandchild saying thank you | 4.7, 17.0, 28.9 s | – | Stayed green (correct) |

It used 11 checks instead of 15, and none failed. What is left: a warning can still come up to about
12 seconds after the words that give a scam away, plus the second or so a check takes. A paid Groq
tier could check more often by lowering `ANALYSIS_INTERVAL_SECONDS`.

## 4. Missed: the "council rebate" that only asks for identity details (`s13`)

**What happened.** A "council revenue team" says you're owed a rebate, but first wants your full name,
date of birth and National Insurance number. The meter stayed green: model risk 30, no red flags.
The model's own reason was right, *"They are asking for personal details you should not give over
the phone"*, but its number sat just under the yellow line of 40, and the meter only shows the reason
for yellow or red. So the person would have seen "No warning signs so far" and never that sentence.

**Why.** The prompt describes scams as money, urgency and secrecy, and every red flag is about money,
codes or access. This call asks for no money yet: it collects identity details first, which real
scams do so they can open accounts or pass security checks later.

**What would fix it.** Make identity details a warning sign in their own right: a sixth red flag such
as "asks for identity numbers (National Insurance, passport, full date of birth) on a call you didn't
expect", or a line in the risk scale that puts it at yellow or above. It needs careful wording,
because the GP surgery case (`n04`) asks for a date of birth and is genuine. Either change means
running every case again and reporting before and after.

**Decision.** Not fixed yet. It is listed as a known limit in the README.

## 5. Near misses, and red flags stretched to fit (`s14` to `s17`)

**What happened.** The other four scams written without red-flag words were all caught, but not the
way the prompt describes. The model reported a red flag in each one by stretching its meaning: a card
payment by link or over the phone (`s14`, `s15`) and reading out a card number (`s17`) were reported
as `unusual_payment`, which the prompt defines as gift cards, crypto, a wire transfer or a courier,
and a pension "scheme" (`s16`) was reported as a `safe_account`. Two of them would have been yellow
without the stretch: `s16` got a risk of 45 and `s17` 55.

**Why it matters.** It helped here, but it means the safety net is looser than written. The same
stretch could turn a genuine card payment, such as a real energy company taking a payment you asked to
make, into a red warning. None of the normal calls tests that yet.

**What would fix it.** Widen the red-flag definitions on purpose, so the behaviour is written down
rather than improvised, and add look-alike normal calls with genuine card payments to measure the
false alarms that might cause.

**Decision.** Not changed yet.

## How far to trust these numbers

- **A smoke test, n = 29.** 16 of 17 scams caught is consistent with a true catch rate anywhere from
  about 73% to 99%, and 1 false alarm in 12 with anything from about 1.5% to 35% (95% Wilson
  intervals). One more case either way moves the catch rate by about 6 points.
- **Text only.** Phone audio, accents, noise and speech-recognition mistakes (beyond two cases) were
  not tested by the 29 cases.
- **Look-alikes on purpose.** 10 of the 12 normal calls were chosen to be hard, so the false-alarm
  rate is likely worse than on everyday calls.
