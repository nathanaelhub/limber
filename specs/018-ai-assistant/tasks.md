# Tasks: AI Assistant, slice A, the therapist assistant (018)

Built test-first. Each task names the tests that pin it. Slice A is the therapist's weekly summary and
draft replies (US1, US2). Slice B, the patient exercise coach (US3), comes later; this slice only stores its
per-patient switch.

- [x] T001 Constitution amendment v1.3.0: Principle III allows one named AI processor (Anthropic) for patient
      text records under the stated guarantees. `.specify/memory/constitution.md`, version 1.3.0, amended
      2026-10-30.
- [x] T002 Dependency: the `anthropic` Python SDK in `requirements.txt` (FR-008, Principle V). `src/assist/`
      is the only package that imports it. Tests: `tests/test_assist.py::TestBoundary` (FR-001).
- [x] T003 Key: read only from `LIMBER_ANTHROPIC_API_KEY`, from the environment or the gitignored `.env`;
      the shell's `ANTHROPIC_API_KEY` is never used and the key is never logged. No key: every AI control is
      hidden and preflight reports "AI assistant: off (no key)". Tests: `TestKey`, `TestPreflight` (FR-002).
- [x] T004 Schema v16: per-patient switches (`assist_switches`, summaries and drafts / exercise coach, both
      off by default); the host call log (`assist_calls`: time, patient, account, purpose, model, input and
      output tokens, outcome, never content); therapist notes (`therapist_notes`, with an AI-drafted marker);
      `messages.from_draft`; `message_handled` for "Mark as handled by phone".
      Tests: `TestSchema`, `tests/test_ptlog_store_v15.py` (FR-007).
- [x] T005 Red-flag screening on the host, from the word list `src/assist/red_flags.txt`.
      Tests: `TestRedFlags` (FR-005).
- [x] T006 Pseudonymised record extract: patient ID, plan title, program, the last 7 days of sessions,
      check-ins, questionnaire scores, messages in the plan, and host transcripts, each with a record ID. No
      display name, username, account field, patient label, notes, or diagnosis.
      Tests: `TestExtract`, `TestNoAccountFieldsInRequests` (FR-006).
- [x] T007 Requests: `claude-opus-5-5`, adaptive thinking, explicit effort, server-side fallbacks
      (`fallbacks: "default"`), the fixed system prompt and the extract first with cache breakpoints.
      `refusal` and `max_tokens` stop reasons, API errors, and invalid output are "unavailable", never shown
      partially. Every call is logged. Tests: `TestRequestShape`, `TestUnavailable`, `TestCallLog`
      (FR-003, FR-004, FR-007).
- [x] T008 Weekly summary (US1): no records means no call; each claim and next step must cite record IDs
      from the extract, and any without one is dropped; at most 3 next steps; the switch off means no call;
      a per-therapist daily cap (setting, default 50). Save as a therapist note marked AI-drafted.
      Tests: `TestWeeklySummary`, `TestDailyCap`, `TestNotes` (US1 scenarios 1–4).
- [x] T009 Draft reply (US2): a draft never sends; withheld when any patient message since the therapist's
      last reply trips the red-flag list; a sent message records whether it began as a draft; "Mark as handled
      by phone" clears the attention flag and is recorded. Tests: `TestDraftReply`, `TestHandledByPhone`
      (US2 scenarios 1–3, FR-009).
- [x] T010 Therapist screens: the summary panel on the patient page (idle, loading, result, saved, no
      records, unavailable); Draft a reply and the withheld notice in the inbox; the AI settings section with
      both switches, the patient notice, and a coach log placeholder. With no key, none of it shows.
      Tests: `tests/test_app_assist.py` (SC-003).
- [x] T011 Patient notice: when a switch is on, the patient's Settings page says in plain words what is sent
      to Anthropic. Tests: `tests/test_portal_assist_http.py`.
- [x] T012 Live smoke test, opt-in (`LIMBER_LIVE_AI=1`), against demo data only:
      `tests/test_assist_live.py`. Demo seed turns the switches on for P-021.

## Slice B, the patient exercise coach (US3)

- [x] T013 Schema v17: `coach_turns` (question, kind shown, answer, exercise, called), removed with the patient; the
      therapist's daily cap no longer counts coach calls. Tests: `tests/test_assist_coach.py::TestSchema`,
      `TestOffAndLimits::test_coach_calls_do_not_use_the_therapists_cap`.
- [x] T014 The program extract: only the signed-in patient's program, under the code, attached to the plan the
      program belongs to. Tests: `TestAnswers::test_the_request_holds_only_this_patients_program`, `TestPlan`
      (FR-006).
- [x] T015 The coach request and answer: `claude-sonnet-5-5`, adaptive thinking, effort low, JSON schema, cache
      breakpoints; set text for referral and refusal; the dose check; refusal, cut-off, errors and bad output are
      unavailable. Tests: `TestAnswers`, `TestReferralAndRefusal`, `TestUnavailable` (US3 scenarios 1–2, FR-003,
      FR-004, edge cases).
- [x] T016 Red flags before anything else, the switch, the daily cap of 20, no program. Tests: `TestEmergency`,
      `TestOffAndLimits` (US3 scenarios 3 and 5, FR-005).
- [x] T017 Portal: `GET/POST /api/coach`, the `/coach` page with every design state, the entry rows on Today and
      Messages, the referral's hand-over into Messages. Tests: `tests/test_portal_coach_http.py`.
- [x] T018 Therapist: the coach log in AI settings, read only, newest day first. Tests:
      `tests/test_app_assist.py::TestCoachLog` (US3 scenario 4).
- [x] T019 Demo seed: the coach on for P-021 with yesterday's simulated conversation. Browser walk at 390px and
      768px, with Larger text, Higher contrast and Less motion, and the therapist log at 1280px, with live answers.
