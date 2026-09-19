# Contract: review summary exports

**Feature**: 002-review-over-time. Both are pure functions of a `ReviewSummary`.

## Text report (`review_report`, `.txt`)

```text
PT REVIEW SUMMARY
Patient: P-017
Period: last 30 days (2026-08-17 to 2026-09-16)
Generated: 2026-09-16 14:02

TRENDS
Knee Extension — 4 sessions
  date        session  reps/target  avg form (0-100)  avg ROM (deg)  avg rep (s)  tempo sd (s)  partial (%)  status
  2026-08-20  12       8/10         85.0              80.0           2.40         0.15          0.0          completed
  ...
  change first→latest: reps +2, avg form +3.0, avg ROM +12.0°, avg rep -0.30 s, tempo sd -0.05 s, partial +10.0 pts
  goal: ROM 120° (latest 92.0°, 77% of goal), reps 10

FLAGS
- [form_declining] Knee Extension: form score fell across sessions 12, 13, 14, 15 (90, 86, 81, 75).
- [practice_gap] 9 days since the last session on 2026-09-07 (threshold 7).
Not evaluated yet: rom_plateau for Squat (needs 4 sessions, has 2)

GOALS
Knee Extension: ROM 120° — latest 92.0° (77%); reps 10 — latest 10/10

SESSIONS
- 2026-09-07 session 15 | Knee Extension 7/10 | reviewed 2026-09-08 10:12 | next step: hold | notes: …
- 2026-09-01 session 14 | Knee Extension 8/10 | pending review
```

Numbers use the units in the column headers; "n/a" for missing values; sections that are
empty say so (`No flags in this period.`, `No goals set.`).

## CSV (`review_csv`, `.csv`)

Header row (units in names), `\r\n` line endings, one row per session per exercise, newest
session first:

```text
date,session_id,exercise,reps_completed,target_reps,avg_form_score_0_100,avg_rom_degrees,avg_rep_duration_seconds,tempo_consistency_seconds,partial_rep_share_percent,interrupted,review_status,next_step,reviewed_at
```

Missing values are empty cells. `review_status` is `reviewed` or `pending`.

## Naming and bookkeeping

`{patient_id}_review_{period}_{YYYYMMDD_HHMMSS}.{txt|csv}` under `exports/` by default;
each file is recorded in `review_exports` so patient deletion removes it.
