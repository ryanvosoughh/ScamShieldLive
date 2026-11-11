# ScamShield Live: write-up

**Track:** Security, with Real-Time Assistance overlap. **By:** Amirhossein Vosough.
**Code and run instructions:** `README.md`. **How I used AI:** `ai.md`. **Numbers:** `eval/results.md`.

## Who it is for and the problem

An older person answers the phone to a voice that is kind, urgent, or both: "Nana, it's me, I'm in trouble, please don't tell Mum, I need gift cards." Or a "bank fraud team" asking for a code. AI voice cloning now makes the first kind sound like family. In the middle of the call she can't type, can't read a long message, and may be too frightened to think.

## Why voice is the right interface

- **The threat is a voice.** The call itself is the only evidence, and it arrives as speech, live.
- **The warning has to reach her mid-call.** Her hands and eyes are busy with the phone, so a spoken warning works where a text alert would be missed.
- **It has to run in real time.** A scam report after the call is too late; the point is to say "hang up, call back on a number you know" before the money moves.

## What I built

A web app you put next to a phone on speaker. It streams the microphone to Deepgram for live text, then every few seconds sends the last 30 seconds of text to a language model on Groq. The answer comes back as strict JSON: a risk number, any red flags (a code, a gift card or crypto payment, a "safe account", remote access), the exact words that raised the alarm, a plain-language reason, and what to do.

A scorer turns that into green, yellow or red: it smooths the numbers, goes straight to red on any red flag, and never goes back to green after red. A failed check shows "Couldn't check the call", never "safe". The page highlights the evidence in the transcript and says the warning out loud, pausing the microphone so the app never transcribes its own voice. Demo mode plays scripted calls and needs no keys, so anyone can run it.

## Results (a smoke test, not proof)

I tested the scam check on 29 short text calls: 17 scams and 12 normal calls, with ten deliberately tricky look-alikes and polite scammers.

| | Result |
|---|---|
| Scams caught | 16 of 17 |
| Normal calls left green | 11 of 12 |
| Time per check | 0.7 s on average, 1.3 s at worst |
| Red after the scammer's request (demo calls, real time) | 7 to 9 s |

The test also caught a real bug: my first pacing spent all its checks on small talk, so one demo scam was never flagged. Spreading the checks evenly fixed it.

## Limits

- **One missed scam:** a "council rebate" that only asked for identity details and never mentioned money.
- **One false alarm:** a grandson helping fix a laptop remotely. The words alone can't tell a relative from a scammer.
- **Small, tidy test set:** with 17 scams, 16 of 17 fits a true catch rate from about 73% to 99%. The cases are text, so phone-quality audio, accents and noise are untested.
- **English only**, and warnings can lag up to about 12 seconds because of the free tier's rate limit.
- **Privacy:** nothing is stored, but audio goes to Deepgram and text to Groq, and some places require consent before a call is transcribed.

## What I would do next

1. Add a signal outside the words: is the caller a saved contact?
2. Treat identity-detail requests as a warning sign, and re-check the final seconds of a call.
3. Add a family safe word, and listen to tone of voice as well as the words.
4. Test on real phone-quality calls with consent, and with older people and their families.
5. Run more of it on the device, and connect it to a real phone line.
