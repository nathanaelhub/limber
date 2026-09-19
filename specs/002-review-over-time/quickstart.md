# Quickstart: Review Over Time

Validation guide. Commands assume the repo venv and a scratch database
(`export PTASSIST_DB=/tmp/review.db`). See [contracts/cli.md](contracts/cli.md).

## 1. Tests

```bash
.venv/bin/python -m pytest tests -q
```

Expected: green, including `test_ptlog_measures.py`, `test_ptlog_flags.py`,
`test_ptlog_review.py`, `test_ptlog_review_exports.py`, the review CLI tests, and the
Review page tests. `tests/test_session_tracker.py` no longer exists.

## 2. Seed sessions

```bash
python interfaces/cli.py patients add P-017 --label "Post-op knee"
python interfaces/cli.py import-legacy --dry-run      # or run a few video sessions with --patient P-017
```

Any patient with three or more sessions of one exercise works; the importer's fixtures under
`tests/fixtures/legacy/` can be imported into the scratch database for a quick history.

## 3. Trends

```bash
python interfaces/cli.py review trends P-017 --exercise "Knee Extension" --period all
```

Expected: one row per session oldest first with reps/target, avg form (0-100), avg ROM (°),
avg rep (s), tempo sd (s), partial (%); a first→latest change block when ≥ 2 sessions.

## 4. Goals and settings

```bash
python interfaces/cli.py review goal set P-017 --exercise "Knee Extension" --rom 120 --reps 10
python interfaces/cli.py review settings P-017 --gap-days 5
python interfaces/cli.py review trends P-017 --exercise "Knee Extension"
```

Expected: the trend now shows the goal and the ROM progress percentage; a ROM of 200 is
rejected.

## 5. Flags

```bash
python interfaces/cli.py review flags P-017 --period all
```

Expected: each flag names its sessions and values; rules without enough sessions are listed
under `Not evaluated yet:`; a practice gap appears if the last session is older than the gap
threshold.

## 6. Review a session and the pending list

```bash
python interfaces/cli.py review pending P-017
python interfaces/cli.py review session <id>
python interfaces/cli.py review mark <id> --next-step progress --notes "post-op week 3, tolerated full set"
python interfaces/cli.py review mark <id> --next-step hold --notes "seen by Jane Doe"    # expect: rejected
python interfaces/cli.py review pending P-017
```

Expected: the session leaves the pending list; `review session` shows the per-session summary
flags plus the review; the name-like notes are rejected.

## 7. Compare

```bash
python interfaces/cli.py review compare <older_id> <newer_id>
```

Expected: a table per measure with both values, change, % change, and which direction is
better; two sessions of different exercises are refused.

## 8. Export

```bash
python interfaces/cli.py review export P-017 --period all --format all --out /tmp/review-exports
```

Expected: `P-017_review_all_<time>.txt` and `.csv` with the sections in
[contracts/exports.md](contracts/exports.md); deleting P-017 afterwards removes both files.

## 9. Web app

```bash
streamlit run interfaces/app.py
```

Expected: a Review page with Trends, Flags, Compare, Session review, Goals & settings, and
Export tabs; the Progress Report and PT Summary pages are gone.

## Done criteria

All steps behave as stated, the suite is green, `docs/UPDATES.md` has an entry, and the
README lists the review commands.
