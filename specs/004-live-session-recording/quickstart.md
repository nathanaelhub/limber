# Quickstart: Live Web Session Recording

## 1. Tests (no camera, no model)

```bash
.venv/bin/python -m pytest tests -q
```

Expected: green, including `tests/test_live_session.py` and the live page render test.

## 2. Parity on a real clip (needs the model; opt-in)

```bash
PTASSIST_E2E=1 PTASSIST_DB=/tmp/live.db .venv/bin/python -m pytest tests/test_live_parity_e2e.py -q
```

Expected: the reps and partial reps a `LiveSession` records for
`videos/Squats.demo.video.mp4` equal those `analyze.main()` records for the same clip
(SC-001).

## 3. Live session in the browser

```bash
export PTASSIST_DB=/tmp/live.db
python interfaces/cli.py patients add P-017 --label "Post-op knee"
streamlit run interfaces/app.py
```

Select P-017 in the sidebar, open Live Session, choose Knee Extension, target 10, start the
stream, perform a few reps, press "Switch exercise" after choosing Squat, press "Reset reps",
press "Save Screenshot", then stop.

Expected: the caption shows `Recording session <id> for P-017`; the panel shows reps, angle,
phase, form status, and messages; a PNG `P-017_<time>.png` appears under `exports/`; on stop
the summary block equals `python interfaces/cli.py sessions show <id>` and "Open in Sessions"
opens the session; the switch and reset appear in the event log; no Save Session control
exists.

## 4. Interruption

Start a stream, complete reps, then kill the Streamlit process. Restart it and run
`python interfaces/cli.py sessions list --patient P-017`.

Expected: the session is listed as interrupted with the reps recorded before the kill.

## 5. Everywhere else

`review trends`, `review flags`, `tracker roster` for P-017 include the live sessions.

## Done criteria

Steps 1, 3, and 4 pass; step 2 passes on a machine with the model; `docs/UPDATES.md` has an
entry.
