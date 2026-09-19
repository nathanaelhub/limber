# Contract: `review` command group

**Feature**: 002-review-over-time. Exit codes: 0 success, 1 user error (validation, not found,
refused comparison), 2 I/O error. `--json` prints JSON on stdout where noted. The `progress`
command is removed.

```text
python interfaces/cli.py review trends <PATIENT> --exercise NAME [--period 14d|30d|90d|all] [--json]
python interfaces/cli.py review flags <PATIENT> [--period ...] [--json]
python interfaces/cli.py review compare <SESSION_A> <SESSION_B> [--exercise NAME] [--json]
python interfaces/cli.py review session <SESSION_ID> [--json]
python interfaces/cli.py review mark <SESSION_ID> --next-step continue|progress|regress|hold [--notes TEXT]
python interfaces/cli.py review pending <PATIENT> [--json]
python interfaces/cli.py review goals <PATIENT> [--json]
python interfaces/cli.py review goal set <PATIENT> --exercise NAME [--rom DEGREES] [--reps N]
python interfaces/cli.py review goal clear <PATIENT> --exercise NAME
python interfaces/cli.py review settings <PATIENT> [--gap-days N]
python interfaces/cli.py review export <PATIENT> [--period ...] --format report|csv|all [--out DIR]
```

- `trends` prints a table with one row per session (date, session, reps/target, avg form
  (0-100), avg ROM (°), avg rep (s), tempo sd (s), partial %) and a summary block (first,
  latest, change) or `A trend needs at least two sessions.`; a goal line when set.
- `flags` prints one paragraph per flag with its evidence, then `Not evaluated yet:` lines
  with the sessions needed, or `Nothing needs attention.`.
- `compare` prints a table: measure, session A, session B, change, % change, better-when.
  Different exercises → exit 1 `Comparisons are within one exercise; …`.
- `session` prints the session header, measures per exercise, the per-session summary flags,
  and `REVIEW: pending` or `REVIEW: reviewed <time> | next step: <x> | notes: …`.
- `mark` prints `Reviewed session <id> (next step: progress)`; invalid notes → exit 1 with the
  rule; unknown session → exit 1.
- `pending` lists newest first: session, date, exercises, reps.
- `goal set` prints `Goal for <exercise>: ROM 120° | reps 12`; out-of-range → exit 1.
- `settings` prints `Gap threshold: 7 days`; with `--gap-days` updates it (1–90).
- `export` prints each path written; default `--period all`, default `--out exports/`.
