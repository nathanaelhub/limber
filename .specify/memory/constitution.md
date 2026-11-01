<!--
Sync Impact Report (temporary; remove before the next amendment)
Version change: 1.2.0 -> 1.3.0 (MINOR: materially expanded guidance, no principle removed)
Rationale: the owner chose to use an Anthropic API key for a therapist assistant (weekly summaries,
draft replies) and a patient exercise coach (feature 018). Principle III forbade third-party
processing; it now allows one named AI processor for patient text records under stated guarantees.
Audio, video, photos, and documents still never leave the host.
Modified: Principle III (new bullet on one named AI processor).
Added sections: none. Removed sections: none.
Follow-ups: specs/018 carries the Constitution Check; the processor's retention terms are stated
there; real-clinic use still waits for the compliance review.
-->

# PT Assist Constitution

PT Assist is an AI physical-therapy assistant that uses YOLO11 pose estimation to count reps,
measure range of motion, and assess exercise form. This constitution governs the brownfield
phase that adds a PT log, a review-over-time process, and a multi-patient PT tracker on top of
the existing computer-vision engine.

## Core Principles

### I. The Engine Is a Dependency, Not a Rewrite Target

The computer-vision engine is the existing, calibrated core and is treated as a stable
dependency for this phase. It consists of `analyze.py` (`ExerciseTracker`, `ExerciseSession`,
`RepMetrics`), `src/form_assessment.py` (`FormAnalyzer`), the angle math in `src/utils.py`,
and the exercise thresholds in `config.yaml`.

- Thresholds, state-machine transitions, angle smoothing, and form checks MUST NOT change
  without an approved spec that names the change and a regression test that fails before the
  change and passes after it. Bug fixes follow the same rule.
- New features MUST consume the engine through its public outputs only: the dictionary
  returned by `ExerciseTracker.update()`, `ExerciseSession`, `RepMetrics`, and the assessment
  objects returned by `FormAnalyzer`. They MUST NOT read tracker internals or re-implement
  angle or rep logic.
- Any new engine-facing seam MUST be added as a small, documented adapter in `src/`, never by
  editing the engine's control flow.

Rationale: the thresholds and fixes in the engine represent months of calibration against real
sessions. Regressions there are silent and clinically misleading, so the engine changes only
under a spec with a test that would catch the regression.

### II. One Canonical Session Record

There is exactly one data model and exactly one writer for patient, session, exercise-set, rep,
and form events.

- Every other format (PTA-Log pipe-delimited text, observation JSON, session JSON and CSV,
  numbered text log files) MUST be an export adapter that is a pure function of the canonical
  record. Adapters MUST NOT be read back as a source of truth.
- The four existing writers (`SessionLogger`, `PTARawLogger`, `ObservationLogger`,
  `SessionTracker`) are legacy. The spec that introduces the canonical record MUST state how
  each one is retired or re-pointed to an adapter. No feature MAY add a new parallel writer.
- Every persisted record MUST carry a schema version, and schema changes MUST ship with a
  migration and a test that reads a record written by the previous version.
- Review-over-time and tracker features MUST read only from the canonical record.

Rationale: the codebase currently writes four overlapping formats with three different
schemas, and there is no patient entity. Reviewing progress over time is impossible without a
single truth.

### III. Local-First and Privacy-Preserving

Patient data stays on the user's machine, and patients are never identifiable from artifacts.

- All data MUST be stored locally by default. No feature MAY send patient data over the network
  unless it is an explicit, separately specified opt-in feature whose spec includes a
  Constitution Check against this principle.
- A networked feature's spec MUST state exactly which data crosses the network, which data
  never does, and who may use the feature. It MUST be off until a therapist turns it on for a
  specific patient, MUST expose to a signed-in patient only that patient's own data, and MUST
  NOT be used with real clinic patients until a compliance review has approved it; until then
  it is limited to demo and consented study participants. During a guided session only body
  points are sent; camera video MUST NOT leave the patient's device then.
- A patient MAY deliberately upload a short video clip or voice note for the therapist, only
  after a plain notice that it is stored on the Limber host and seen by the therapist. Such
  uploads MUST be a separately specified feature, stored only under the pseudonymous ID,
  subject to a stated retention period, deletable by the patient and deleted with the patient,
  and processed (for example transcribed) only on the Limber host, never by a third-party
  service. An installed patient app MAY keep a device signed in for up to 30 days, revocable by
  the therapist at any time.
- A feature MAY send a patient's text records (logs, diary, questionnaire answers, messages, and
  transcripts produced on the host) to one named AI processor, only if: it is off until the
  therapist turns it on for that patient; the patient has been told in plain words that their
  records are processed by that service; requests carry the pseudonymous ID and never the display
  name, username, or any account field; no audio, video, photo, or document is sent; every request
  and response is logged on the host with its size and purpose, without its content; and the
  processor's data-retention terms are stated in the feature's spec. The named processor is
  Anthropic (Claude API). Real clinic patients still require the compliance review.
- Patients MUST be identified by pseudonymous IDs. Names, dates of birth, medical record
  numbers, and contact details MUST NOT appear in filenames, log lines, screenshots, test
  fixtures, commit messages, or committed files.
- Data directories (`sessions/`, `observation_logs/`, `pta_logs/`, `logs/`, `data/media/`, and the
  canonical store) MUST remain gitignored. Test fixtures MUST be synthetic.
- Deleting a patient MUST remove every record and export tied to that patient's ID.

Rationale: this tool is used in a graduate-assistant clinical setting where patient data is
protected health information. Local-first storage and pseudonymous IDs keep the default
posture safe without a compliance program.

### IV. Test-First (NON-NEGOTIABLE)

Every feature is specified by tests before it is implemented.

- Each spec MUST ship with tests that fail before implementation and pass after it. A task is
  not done until its tests pass.
- The full suite MUST stay green. The reference command is
  `.venv/bin/python -m pytest tests`, and it MUST pass before any commit.
- The engine's tests (`tests/test_analysis.py`, `tests/test_form_assessment.py`) are the
  regression guard. They MUST NOT be skipped, marked expected-failure, or loosened to make new
  work pass. A test in those files MAY change only under Principle I.
- Tests MUST run without camera hardware, without network access, without a browser, and
  without any model weights (pose or speech) in `models/` or elsewhere. Data-layer tests MUST use temporary directories or in-memory stores and
  MUST NOT write into the project's data directories.

Rationale: the engine has 98 passing tests that protect calibrated behaviour; the new data
layer will be trusted by clinicians only if its behaviour is pinned the same way.

### V. Simplicity and Clinical Readability

Prefer the simplest tool that already exists, and make every number a clinician can read.

- Prefer the standard library and dependencies already in `requirements.txt` (`sqlite3`,
  `pandas`, Streamlit, matplotlib) over new frameworks. A new dependency MUST be justified in
  the plan's Complexity Tracking section with the simpler alternative that was rejected.
- Every metric surfaced to a physical therapist MUST have a defined unit and a plain-language
  definition, in the code docstring and in the UI (for example, range of motion in degrees,
  form score from 0 to 100). Undefined metrics MUST NOT be displayed.
- No feature ships without an entry in `docs/UPDATES.md` describing what changed and how to
  use it.
- YAGNI applies: no ORM, authentication system, plugin architecture, or abstraction for a
  hypothetical future need until a spec requires it.

Rationale: the users are physical therapists and students, not engineers. Fewer moving parts
and clearly defined numbers make the tool trustworthy and maintainable by a small team.

## Technical Constraints & Reference Environment

- **Reference environment**: Python 3.13 in the repo-local virtual environment at `.venv`,
  created from `/opt/homebrew/bin/python3.13`. `requirements.txt` is the single dependency
  manifest; new dependencies MUST be added there with a lower-bound pin. Python 3.14 is not
  supported until torch publishes wheels for it.
- **Canonical store**: the canonical session record MUST persist to a single local file.
  SQLite through the standard library `sqlite3` module is the default choice; a plan MAY choose
  otherwise only with a justification under Principle V.
- **User interface**: the Streamlit app in `interfaces/app.py` and the CLI in
  `interfaces/cli.py` remain the therapist's interface surfaces for this phase. The patient
  portal in `interfaces/patient_portal.py` is the one patient-facing surface; it is a separate
  launch that contains no therapist pages. Business logic MUST live in `src/` and be testable
  without Streamlit or a running server; interface code only renders and dispatches. Browser
  JavaScript MUST stay free of clinical logic (rep counting, form wording, program order), so
  that behaviour is covered by the Python test suite.
- **Engine surface**: the public outputs listed in Principle I are the only supported
  integration points. The model weights file `models/yolo11m-pose.pt` is a runtime
  requirement, never a test requirement.
- **Data layout**: all patient-scoped data lives under gitignored directories. Exports MUST be
  written to a location the user chooses, defaulting to a gitignored directory.

## Development Workflow & Quality Gates

- **Spec-driven flow**: every feature follows constitution → specify → clarify → plan →
  tasks → analyze → implement. `spec.md`, `plan.md`, and `tasks.md` MUST each include a
  Constitution Check that lists every principle with a pass mark or a written
  justification.
- **Sequencing**: a feature that reads or writes session data MUST NOT begin implementation
  before the canonical session record (Principle II) is implemented and its tests pass. The
  intended order is the canonical record, then review over time, then the PT tracker.
- **Branching and commits**: one feature branch per spec, created by the Spec Kit scripts.
  Commits happen only with a green suite and only when requested. Commits MUST NOT include
  data directories, model weights, or anything covered by Principle III.
- **Definition of done** for a feature: all tasks complete; new tests fail-then-pass recorded;
  full suite green; Constitution Check passed in `/speckit-analyze`; `docs/UPDATES.md` entry
  written; README updated when setup or usage changes.
- **Review gates** for any merge: no new parallel writer; no engine change without a spec and
  regression test; no metric without unit and definition; no PHI in the diff.

## Governance

- This constitution supersedes ad-hoc practice and any other project document where they
  conflict. `README.md` and `docs/PROJECT_OVERVIEW.md` provide runtime and onboarding guidance
  and MUST be kept consistent with it.
- **Amendments** require a written rationale, an updated Sync Impact Report, a version bump,
  and an updated Last Amended date. Versioning follows semantic versioning: MAJOR for removing
  or redefining a principle in a backward-incompatible way, MINOR for adding a principle or
  section or materially expanding guidance, PATCH for clarifications and wording.
- **Compliance review**: every spec, plan, and task list is checked against this document
  before implementation begins, and `/speckit-analyze` MUST be run after task generation. A
  violation is either fixed or justified in the plan's Complexity Tracking section; unjustified
  violations block implementation.
- **Exceptions** are temporary, recorded in the affected `plan.md` with an expiry condition,
  and revisited at the next amendment.

**Version**: 1.3.0 | **Ratified**: 2026-09-14 | **Last Amended**: 2026-10-30
