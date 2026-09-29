# Feature 015: Spoken Answers During an Exercise — Dropped

**Status**: **Dropped on 2026-09-29** by the owner's decision, with the reasoning below.

**Never branched, never implemented.** This file exists so that the reasoning survives the decision, for
the compliance review and for whoever picks the idea up later.

## What it was going to be

The patient, mid-exercise with their phone propped up and their hands busy, answers out loud instead of
tapping: "how does that feel?" → "sore", "done", "stop". It was the last of the five phone features the
owner approved on 2026-09-23, at the lowest priority, already flagged there as "decided after 014 is in
use".

## Why it cannot be built as specified

1. **The browser's speech recognition sends the patient's voice to Apple or Google.** `SpeechRecognition`
   in Safari and Chrome is a service, not an on-device feature: the audio leaves the phone to be
   recognised. Constitution Principle III forbids exactly that — patient data never goes to a third
   party — and a voice is more identifying than anything else Limber handles. This is not a detail that
   could be worked around with a setting; it is what the API is.
2. **Recognising speech on the host, live, is beyond the reference host.** Feature 014's writing out
   takes a separate process, up to ten minutes for a three-minute recording, and 1-2 GB of memory while it
   runs. Doing it continuously, while the same 4 GB host runs the pose estimation for the live session, is
   not a tuning problem.
3. **Streaming audio during a session would undo feature 014's own guarantee.** Voice notes are a
   *deliberate* upload after a plain notice. A microphone open throughout an exercise is the opposite of
   deliberate, and the notice could not honestly say what was being sent.

## What would have to change first

- **On-device keyword spotting**: a small model running entirely in the patient's browser, recognising a
  handful of fixed words ("done", "stop", "hurts") with no audio leaving the phone. That is
  constitutional, and it is a research task with an uncertain result rather than a feature — the model
  would have to be small enough to ship, accurate enough to trust with "stop", and no worse for an
  accented or pained voice than tapping a button.
- **Or a host with real capacity** and a compliance review that has looked at continuous audio, which is
  a much larger conversation than this feature.

## What was kept instead

Feature 014 gives the patient the useful half of the same idea, within the rules: they say what they want
to say when they choose to, it is stored on the Limber host and nowhere else, and the therapist hears it.
The hands-free part — answering during the movement itself — is what has been dropped.

## Decision

Dropped. Not deferred: if on-device keyword spotting is ever attempted it will be a new feature with its
own spec, not this one resumed.
