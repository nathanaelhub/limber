# Contract: `tracker` command group

**Feature**: 003-pt-tracker. Exit codes: 0 success, 1 user error, 2 I/O error. `--json`
prints JSON where noted.

```text
python interfaces/cli.py tracker roster [--sort attention|id] [--program ID] [--needs-attention] [--json]
python interfaces/cli.py tracker programs [--json]
python interfaces/cli.py tracker assign <PATIENT> (--program ID | --exercises k1,k2,...) [--per-week N] [--start YYYY-MM-DD] [--end YYYY-MM-DD]
python interfaces/cli.py tracker assignments <PATIENT> [--json]
python interfaces/cli.py tracker adherence <PATIENT> [--json]
python interfaces/cli.py tracker queue [--json]
python interfaces/cli.py tracker settings [--adherence-threshold N]
python interfaces/cli.py tracker discharge <PATIENT> [--on YYYY-MM-DD] [--reason TEXT]
python interfaces/cli.py tracker reactivate <PATIENT>
python interfaces/cli.py tracker discharged [--json]
python interfaces/cli.py tracker export-roster [--out DIR]
```

- `roster` prints one row per active patient: patient, label, program (status), last session
  (days), 7d, 30d, adherence (%), pending, flags, gap, next step; default sort attention.
- `programs` lists id, name, exercise count, exercises (display names), and `custom`.
- `assign` prints `Assigned <program name> to <patient>: <n> sessions/week from <start>[ to <end>]`
  and, when a previous assignment was ended, `Ended previous assignment (<name>) on <date>`.
  Unknown keys, per-week outside 1–14, end before start, or the built-in patient → exit 1.
- `assignments` lists the history newest first with status.
- `adherence` prints the assignment line, one row per week (`week 3  2026-09-01..2026-09-07
  1/3  missed | performed: knee_extension | missing: partial_squat`), the current week as in
  progress, and `Adherence: 44% over 3 complete weeks` or the note.
- `queue` prints sections per kind with counts, each item as `- <patient> | <description> |
  <target>`, or `Caseload is up to date.`
- `settings` prints `Adherence threshold: 60%`.
- `discharge` prints `Discharged <patient> on <date>`; `reactivate` prints `Reactivated <patient>`
  or `<patient> is already active`.
- `export-roster` prints the path written.
