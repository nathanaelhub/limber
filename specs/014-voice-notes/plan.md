# Implementation Plan: Voice Notes, with a Transcript for the Therapist

**Branch**: `014-voice-notes` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

*(As in features 010-013, the design artefacts the template lists separately are folded into this file
and `tasks.md`: there is nothing unresolved to research, and the contract is a handful of routes plus
one new table pair.)*

## Summary

Audio rides the feature 011 pipeline, which already reserved a `voice` kind in `src/media/probe.py`
(180 s, 10 MB, no video stream). A sent voice note becomes a **message** from the patient carrying a
media id, so the inbox, unread counts, and message removal work unchanged. Schema v13 adds
`media_id` to `messages` and a `transcriptions` table. The therapist plays the note in the inbox thread
and can mark it reviewed or delete it; the work queue gains `new_voice_notes`.

**The feature is built in two slices that ship separately.** Slice A (User Stories 1 and 2) needs no new
dependency and no model files. Slice B (User Story 3) adds transcription, which needs a new runtime
dependency and about 100-500 MB of model files on the owner's machine. **The plan stops before
installing anything and asks the owner**, because installing a dependency and downloading model weights
onto their computer is their decision, not mine. With no model installed, the installation behaves
exactly as after Slice A, and one plain line says writing out is not available.

## The dangerous parts, and how they are made safe

1. **Audio is more identifying than a body point.** A voice can be recognised. So: the notice comes
   before the microphone opens, nothing leaves the host (no browser speech API, no third-party service),
   the transcript is therapist-only, and retention and patient-deletion apply as they do to clips.
2. **A malformed audio file.** The isolated subprocess probe from feature 011 already covers this; the
   `voice` limits need the extra containers phones actually produce (MP3 and WAV), an audio-specific
   refusal for a file that carries video, and a reason word for "no audio".
3. **A worker thread inside the web service.** One thread, one job at a time, a time limit per job, and
   every state change written to the record, so a crash leaves a `failed` row with a reason word rather
   than a job stuck at `running` for ever. The worker holds no lock across a transcription, and the
   service must keep answering while it runs (SC-005).
4. **Model files.** Fetched by `scripts/fetch_speech_model.py` against pinned SHA-256 hashes, stored under
   `models/` (already gitignored), refused on mismatch, never committed. The suite must pass with no
   model present, so every transcription test uses a fake transcriber.
5. **A transcript is not the record.** The audio is. The transcript is always marked automatic and
   possibly wrong, goes through the privacy check, and can be removed by the therapist.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine | PASS | Untouched. |
| II. One record | PASS | One writer; forward-only v13; `media_id` on `messages` is a new nullable column (no rebuild), `transcriptions` a new table. |
| III. Privacy (1.2.0) | PASS | Deliberate upload after a notice; host-only processing, explicitly no browser or third-party speech service; therapist-only transcript; retention and cascade as for clips. |
| IV. Test-first | PASS | Probe, upload, message-with-audio, worker, and the therapist view each get failing tests first; **no model weights and no network in the suite** — a fake transcriber and PyAV-generated audio fixtures. |
| V. Simplicity | **PASS with a justified dependency (Slice B only)** | See below. Slice A adds no dependency. |

### Constitution V: the one new dependency (Slice B)

- **What**: `faster-whisper` (CTranslate2 build of Whisper), CPU, int8, small or base model.
- **Why it cannot be avoided**: the alternatives are a third-party speech service (forbidden by
  Principle III), the browser's speech API (sends audio to Apple or Google — the same rule, and the
  reason feature 015 was re-scoped), or writing a speech recogniser (absurd).
- **Why this one**: it runs on the processor without a graphics card, loads local model files with no
  network call at run time, is several times faster and lighter than the reference Whisper
  implementation, and has a small API surface (one call returning segments).
- **Cost**: about 100-500 MB of model files depending on size, and roughly 1-2 GB of memory while
  running, next to Streamlit and torch on a 4 GB reference host. Sized in `docs/DEPLOYMENT.md`.
- **Containment**: imported lazily inside the worker, absent means the feature degrades to "not
  available", it appears in preflight and health as **optional**, and it is never imported by the suite.

## Structure

```text
src/media/probe.py            # voice limits: add mp3 and wav; reasons for no_audio and has_video
src/media/transcribe.py       # Slice B: the lazy model wrapper and a fake for the tests
src/portal/uploads.py         # a finished voice upload becomes a message with a media id
src/portal/messages.py        # send a message carrying audio; transcripts never reach the patient
src/ptlog/store.py            # v13: messages.media_id, transcriptions table; queue and worker state
src/ptlog/models.py           # Transcription; QUEUE_KINDS gains new_voice_notes
src/ptlog/tracker.py          # unreviewed voice notes on the roster and in the queue
interfaces/patient_portal.py  # /voice page, /api/media accepts the voice kind, message with audio
interfaces/portal_static/voice.html + voice.js     # MediaRecorder, notice first, listen back, progress
interfaces/app.py             # inbox: player, transcript (or "not available"), review, delete, remove text
interfaces/cli.py             # `media transcribe` (run the queue once) and `media transcripts`
scripts/fetch_speech_model.py # Slice B: pinned hashes, refuses a mismatch, writes under models/
```

## Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Where a voice note lives | A `messages` row with a `media_id` | The owner asked for it in the inbox; reusing the conversation means unread counts, removal, and the therapist's reply all work with no new code |
| Schema | `messages.media_id` (nullable) and a `transcriptions` table | Both are additive: no CHECK constraint changes, so no table rebuild this time |
| Recording in the browser | `MediaRecorder` with whatever container the phone gives, plus a file picker as a fallback | iOS and Android produce different containers; the host decides by inspecting the file |
| Queue | Rows in the record, one worker thread, one job at a time, 10-minute limit | A small host; the record is already the single source of truth, and a queue in it survives a restart |
| When the worker runs | Started by the portal process when a model is installed; also runnable once from the CLI | The CLI path is what the tests and the runbook use; no scheduler |
| Model files | `models/`, fetched by a pinned, hash-checked script | `models/` is already gitignored (the pose model lives there); a hash check is the only way to know what was downloaded |
| Transcript visibility | Therapist only, never in a patient response | A transcript is the therapist's reading aid; the no-leak test covers it |
| Failure | A `failed` row with a reason word, visible in the therapist's view | Silence would look like "still working" for ever |

## Slices and the stopping point

1. **Slice A — a voice note that arrives and plays** (US1, US2). No new dependency, no model. Ends with
   the browser run and a merge, so the owner has something usable even if Slice B never happens.
2. **STOP and ask the owner** before installing `faster-whisper` or downloading model files. The ask is
   one question with the cost stated. Nothing in Slice A depends on the answer.
3. **Slice B — the transcript** (US3), only on a yes: the fetch script, the worker, the therapist view,
   preflight and health as optional, the runbook, and a fake transcriber in the suite.

## Risks

1. **Phone recording is uneven.** iOS Safari's `MediaRecorder` support has been late and partial; the file
   picker fallback and the host-side inspection are the mitigation, and only a real phone settles it.
2. **Transcription quality on a small model.** Accents, pain, background noise. Mitigated only by always
   keeping and offering the audio, and by marking the transcript automatic.
3. **Memory on the reference host.** 1-2 GB while transcribing, next to Streamlit and torch. Sized in the
   runbook; the worker is one thread and the model is loaded once and released when idle.
4. **A transcript is quotable.** Someone may paste it into a record elsewhere. The privacy check, the
   marker, and the removal button reduce but do not remove that.
5. **Scope.** No spoken answers during exercises, no translation, no speaker separation, no summary.
