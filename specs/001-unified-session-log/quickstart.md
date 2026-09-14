# Quickstart: Unified PT Session Log

Validation guide for the feature. Every step names the expected outcome. Paths are relative
to the repo root. See [contracts/cli.md](contracts/cli.md) for full command syntax and
[data-model.md](data-model.md) for what is stored.

## Prerequisites

```bash
source .venv/bin/activate            # Python 3.13 venv with requirements installed
python -c "import ultralytics, cv2"  # engine imports work
ls models/yolo11m-pose.pt            # needed only for the live/video steps, not for tests
```

## 1. Tests prove the record without hardware

```bash
.venv/bin/python -m pytest tests -q
```

Expected: all tests pass, including `test_ptlog_*` files; the engine suites
`test_analysis.py` and `test_form_assessment.py` are unchanged and green. No test touches a
camera, the network, the model weights, or the project's data directories.

## 2. Register a patient

```bash
python interfaces/cli.py patients add P-017 --label "Post-op knee"
python interfaces/cli.py patients add "John Smith"        # expect: rejected, exit 1
python interfaces/cli.py patients list
```

Expected: `P-017` listed with 0 sessions; the second command prints the FR-014 reason.

## 3. Record a session from a video (no camera needed)

```bash
python analyze.py video --input videos/<any sample>.mp4 --exercise squat --patient P-017
python interfaces/cli.py sessions list --patient P-017
```

Expected: the run ends with `Session <id> saved for patient P-017 (<n> reps)`; the list
shows one session, source `video`, newest first. The folders `sessions/`, `observation_logs/`,
`pta_logs/`, and `logs/` gain **no new files** (SC-006).

## 4. Read the event log

```bash
python interfaces/cli.py sessions show <id>
```

Expected: header, every rep with `ROM x°`, `form y/100`, `z s`, any partial reps and form
messages in time order, then the summary; values match what the on-screen panel showed.

## 5. Crash safety (webcam optional; video works too)

Start a webcam session, complete a few reps, then kill the process (`kill -9 <pid>` from
another terminal). Then:

```bash
python interfaces/cli.py sessions list --patient P-017
python interfaces/cli.py sessions show <id>
```

Expected: the session is present with `STATUS: interrupted`, every rep completed more than one
second before the kill is listed, and the summary is computed from those reps (SC-002).

## 6. Export in the four legacy formats

```bash
python interfaces/cli.py export <id> --format all
head -14 exports/P-017_*.txt          # PTA header block + first observation lines
python -c "import json;d=json.load(open(sorted(__import__('glob').glob('exports/P-017_*.json'))[-1]));print(d['summary'])"
```

Expected: four files under `exports/` named with the pseudonymous ID and start time only
(the text log is numbered `..._01.log`);
structures match [contracts/exports.md](contracts/exports.md); exporting twice yields
identical files (US4 scenario 4).

## 7. Import legacy history once

```bash
python interfaces/cli.py import-legacy --dry-run
python interfaces/cli.py import-legacy
python interfaces/cli.py import-legacy          # second run
python interfaces/cli.py sessions list --patient unassigned
```

Expected: the first real run reports one `imported` line per legacy session (the repo
currently holds 4 JSON session reports and 2 observation logs); the second run reports them
all as `duplicate (already imported)` and creates nothing (SC-007).

## 8. Web app reads from the record

```bash
streamlit run interfaces/app.py
```

Expected: a Patients page lists `unassigned` and `P-017`; a Sessions page lists sessions newest
first with export download buttons; the Observation Logs, Session Logs, and PT Summary pages
show the same sessions and no longer read the legacy folders (FR-020).

## 9. Delete a patient

```bash
python interfaces/cli.py patients delete P-017
ls exports/ | grep P-017 || echo "no exports left"
```

Expected: confirmation prompt, then counts removed; no sessions, events, or export files for
`P-017` remain (SC-009). `patients delete unassigned` is refused.

## Done criteria

All nine steps behave as stated, the full test suite is green, `docs/UPDATES.md` has an entry
for this feature, and the README documents `--patient` and the new subcommands.
