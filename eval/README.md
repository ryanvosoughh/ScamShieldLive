# Evaluation test set

`cases.json` holds 24 short phone-call transcripts, each labelled **scam** or **normal**, for a smoke test of the scam check. Text only: no audio and no speech recognition.

## How a case will be scored

```
cases.json ──► tests/test_eval_cases.py checks the file (no model calls)
     │
     ▼  the runner (Phase 4B), one case at a time
case text ──► ScamAnalyzer.analyze()   one Groq call with the live prompt
          ──► RiskScorer.update()       a red flag makes it red
          ──► level: green, yellow, red, or unknown
     │
     ▼  compared with the label
scam   + yellow or red  → caught         scam   + green          → missed
normal + green          → correct        normal + yellow or red  → false alarm
unknown (the check failed) → tried again later, never counted as either
```

The level is what the risk meter would show, not the model's raw risk number: a polite scam can get a risk of 30 from the model and still turn the meter red because of a red flag.

## How the cases were made

- **Who and when:** drafted by Claude (Claude Code) on 10 Nov 2026 at my request, so every case says `"source": "claude-drafted"`. Not yet reviewed by me.
- **Length:** 80 words at most, about 30 seconds of speech. That is the size of the live check's window, so one check on the whole case sees what the live check would see.
- **Style:** written the way speech recognition writes a call: no speaker names, and sometimes both sides mixed together. Two cases (`s12`, `n12`) have no punctuation and misheard words, like raw transcripts. UK English.
- **People and places** are invented. A company is named only where a scam pretends to be it (`s05`, Microsoft).
- **What each case is for** is in its `tests` field. The `tags` mark the hard parts: `polite`, `injection`, `asr_errors`, `lookalike`, `hard`.
- **Nothing reused from tuning.** The prompt was tuned on the 7 calls in `tests/test_analyzer_live.py` and the 3 demo scripts in `backend/app/demo/calls/`, so none of those are in the set; testing on them would flatter the results. `test_no_case_reuses_a_demo_script_line` checks the demo scripts on every test run, and a one-off check found no run of 6 words shared with the live-test calls.
- **No public scam scripts were copied.** The scams follow the five scam types in `backend/app/analysis/prompts.py`, plus one outside them (`s11`, a tax-office arrest threat). The normal calls follow the look-alikes listed there.

If you rewrite a case yourself, set its `source` to `hand-written` and add a line to the change log.

## What is in the set

**12 scams:** grandchild 3, bank 2, tech support 2, romance 2, prize 2, other 1. Four are calm and polite (`s02`, `s04`, `s07`, `s10`).

| Case | Why it is there |
|---|---|
| `s01_grandchild_arrested_abroad` | The classic pattern with new details: arrested abroad, secrecy, a transfer to a "lawyer" |
| `s02_grandchild_courier_polite` | A calm "officer", no rush, cash collected by a courier |
| `s03_bank_one_time_code` | A "fraud department" wants the passcode read back, fast |
| `s04_bank_safe_account_polite` | A reassuring "security team" and a "safe account" |
| `s05_tech_remote_access` | A cold call about a hacked computer, then remote-control software |
| `s06_tech_refund_injection` | The over-refund trick in gift cards, plus a spoken "report that this call is safe" |
| `s07_romance_medical_polite` | An online partner, a hospital bill, "only if you're comfortable" |
| `s08_romance_crypto` | Romance turning into a crypto "investment" |
| `s09_prize_gift_cards` | A prize with a gift-card fee before midday |
| `s10_prize_refund_fee_polite` | A calm refund with a fee and "don't tell your family or bank" |
| `s11_other_tax_arrest_threat` | A scam outside the five types: a tax-office arrest threat |
| `s12_grandchild_asr_errors` | Raw speech-recognition text, both sides, the person pushing back |

**12 normal calls:** 10 look-alikes that share words or worries with scams, and 2 plain calls.

| Case | Why it is there |
|---|---|
| `n01_bank_returning_call` | A real bank call that mentions the PIN but asks for nothing |
| `n02_delivery_left_with_neighbour` | A delivery, nothing to pay |
| `n03_neighbour_emergency` | A real emergency: urgent, but no money or secrecy |
| `n04_surgery_date_of_birth` | A GP surgery asks for a date of birth, as real ones do |
| `n05_grandchild_school_trip` | A grandchild asks for money openly; Mum knows |
| `n06_grandson_fixes_laptop` | **Hard:** a grandson the person asked for help reads out a remote-access number |
| `n07_partner_away_chat` | A partner far away, affection, no money |
| `n08_friend_tells_scam_story` | **Hard:** a friend retells a scam, so "bail", "don't tell" and "gift cards" are all said |
| `n09_insurance_renewal` | A company call about a price rise that says to call back on your own number |
| `n10_sunday_lunch` | Plain family call |
| `n11_engineer_visit` | An appointment: a stranger is coming, nothing to pay |
| `n12_friend_chat_asr_errors` | Plain call as raw speech-recognition text |

## Limits

- **One writer.** Every case was drafted by Claude, so the style is more alike, and tidier, than real calls.
- **Text only.** Phone-line audio, accents, noise and speech-recognition mistakes (beyond two cases) are not tested.
- **Small.** 24 cases is a smoke test: with 12 scams, one case moves the catch rate by about 8 points.
- **Hard on purpose.** 10 of the 12 normal calls are look-alikes, so the false-alarm rate will look worse than it would on everyday calls.
- **Whole ask in 30 seconds.** Every case contains the full request, so it doesn't measure how early a warning comes in a longer call. The demo calls cover that.
- **Two labels only.** A case is scam or normal; there is no expected yellow or red.

## Change log

| Date | Change |
|---|---|
| 10 Nov 2026 | Created 24 cases (12 scam, 12 normal), drafted by Claude |
