# Tasks: Voice Notes, with a Transcript for the Therapist

Test-first throughout (constitution IV): every implementation task has a failing-test task before it,
and the suite keeps no model weights, no network, no browser, and no camera. `[P]` marks work in
different files from the task beside it. One commit per green checkpoint.

**Slice A (T001-T014) needs no new dependency.** T015 is a stop: the owner decides about installing
`faster-whisper` and downloading model files before any of Slice B (T016-T023) is built.

## Phase 1: Setup

- [x] T001 Branch `014-voice-notes`; spec; plan; tasks

## Phase 2: Foundational — audio through the existing pipeline

- [x] T002 [P] Audio fixtures in `tests/fixtures/media.py` (m4a/aac, mp3, ogg/opus, wav, webm/opus, a
      silent file, an audio file carrying a video stream, a truncated one) and failing tests in
      `tests/test_media_probe.py`: each accepted container reports its codec and length; a file with a
      video stream is refused `has_video`; a file with no audio is refused `no_audio`; over-long and
      over-large are refused; a damaged file is refused; the isolated probe still survives a crash
- [x] T003 Implement the `voice` limits and reasons in `src/media/probe.py`
- [x] T004 [P] Failing `tests/test_ptlog_store_v13.py`: schema v13 adds `transcriptions` (the message
      link needed no column: `media.message_id` has existed since feature 011); a v12 record upgrades with every table's count intact; a message may carry a media
      id; deleting a patient removes messages, media, and transcriptions; deleting a media row leaves the
      message with a marker
- [x] T005 Implement the v13 migration and the store methods

## Phase 3: User Story 1 — the patient sends a spoken note (P1) 🎯 MVP

- [ ] T006 [P] [US1] Failing tests in `tests/test_portal_voice.py`: finishing a `voice` upload creates one
      message from the patient carrying the media id and raises the therapist's unread count; the audio is
      stored under `data/media/<patient>/`; refusals store nothing and leave no message; a patient hears and
      deletes only their own note; deleting removes the file and leaves the message marked; refused when
      messaging is off or the patient is discharged; the no-leak walk covers the audio routes
- [ ] T007 [US1] Implement the voice branch in `src/portal/uploads.py` and `src/portal/messages.py`, and
      the routes in `interfaces/patient_portal.py`
- [ ] T008 [P] [US1] Failing tests: Today offers a voice note only when messaging is on; the patient's
      conversation carries the player and the length
- [ ] T009 [US1] Implement `interfaces/portal_static/voice.html` and `voice.js` (notice before the
      microphone, record, listen back, re-record, progress, resumption, the file-picker fallback, a plain
      message when the microphone is refused) and the Today and Messages entry points

## Phase 4: User Story 2 — the therapist listens in the inbox (P1)

- [ ] T010 [P] [US2] Failing tests: queue kind `new_voice_notes` and the roster mark in
      `src/ptlog/tracker.py`, counted separately from clips
- [ ] T011 [US2] Implement the tracker changes and the queue label
- [ ] T012 [P] [US2] Failing AppTest: the inbox thread shows the player with length and time, "Mark
      reviewed" clears the queue entry, "Delete" removes the file and leaves a marker, and the reply box
      still works
- [ ] T013 [US2] Implement in `interfaces/app.py`

## Phase 5: Slice A finish

- [ ] T014 Demo voice note in `scripts/seed_demo.py`; `docs/UPDATES.md` Update 16 (Slice A); browser run
      in Chrome with a fake microphone (notice, record, send, the inbox playing it); record what was
      verified; full suite; commit and merge

## Phase 6: The stop

- [ ] T015 **Ask the owner** whether to install `faster-whisper` (about 100-500 MB of model files, 1-2 GB
      of memory while running, on their machine and on the host), stating that Slice A already works and
      that the installation runs without it. Do not install anything before the answer.

## Phase 7: User Story 3 — the transcript, on the host (P2, only on a yes)

- [ ] T016 [P] [US3] Failing tests in `tests/test_media_transcribe.py` with a **fake** transcriber: the
      queue takes one job at a time; a job records queued → running → done with its duration and model; a
      failure records `failed` with a reason word; a job over the time limit is marked `timeout`; the
      transcript goes through the privacy check and carries a marker; an empty result says "nothing
      recognisable"; with no model installed nothing is queued and nothing fails
- [ ] T017 [US3] Implement `src/media/transcribe.py` (lazy import, model absent means unavailable) and the
      queue and worker in the store
- [ ] T018 [P] [US3] Failing tests: `scripts/fetch_speech_model.py` refuses a hash mismatch, writes under
      `models/`, and reports what it wrote (tested against a local file, no network)
- [ ] T019 [US3] Implement the fetch script with pinned hashes
- [ ] T020 [P] [US3] Failing tests: the therapist sees the transcript marked automatic, can remove its
      text, and sees a failure reason; the patient never sees a transcript (no-leak walk); preflight and
      health report the speech model as optional
- [ ] T021 [US3] Implement the therapist view, the CLI (`media transcribe`, `media transcripts`),
      preflight, and health
- [ ] T022 [US3] Install the dependency, fetch the model, and run it once end to end on a real recording;
      record what the transcript actually looked like, honestly
- [ ] T023 Docs (Update 16 completed), `docs/DEPLOYMENT.md` memory and model notes; full suite; commit and
      merge

## Dependencies

- T002-T005 block everything.
- US1 (T006-T009) before US2 (T010-T013): the therapist needs a stored note to listen to.
- T014 closes Slice A; T015 gates Slice B entirely.
- Within Slice B: the queue and worker (T016-T017) before the therapist view (T020-T021); the fetch script
  (T018-T019) is independent and can be written beside them.

## MVP

Slice A: a patient records a spoken note and the therapist hears it in the inbox. The transcript is an
improvement on top, and the installation must run identically without it.
