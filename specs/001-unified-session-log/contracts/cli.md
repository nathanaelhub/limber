# Contract: Command-line interface

**Feature**: 001-unified-session-log

Two entry points exist today and both keep working: `analyze.py` (engine runner documented in
the README) and `interfaces/cli.py` (friendly wrapper). New flags and subcommands below. All
output is plain text; `--json` switches list/show commands to JSON on stdout. Exit code 0 on
success, 1 on a user error (validation, not found), 2 on an I/O error (database unwritable).

## Recording

```text
python analyze.py webcam --exercise <key> [--patient <ID>] [--camera N] ...
python analyze.py video  --input <file> --exercise <key> [--patient <ID>] ...
python interfaces/cli.py webcam  --exercise <key> [--patient <ID>] ...
python interfaces/cli.py analyze --video <file> --exercise <key> [--patient <ID>] ...
```

- `--patient` is optional; omitted → session recorded under `unassigned` (FR-015).
- Unknown patient ID → exit 1 with `Patient '<ID>' not found. Register it with: patients add <ID>`.
- On exit the runner prints `Session <id> saved for patient <ID> (<n> reps)`.
- The legacy `--report` flag on `cli.py analyze` is removed; use `export`.

## Patients

```text
python interfaces/cli.py patients add <ID> [--label TEXT] [--notes TEXT]
python interfaces/cli.py patients list [--json]
python interfaces/cli.py patients edit <ID> [--label TEXT] [--notes TEXT]
python interfaces/cli.py patients delete <ID> [--yes]
python interfaces/cli.py patients reassign <SESSION_ID> --to <ID>
```

- `add` prints `Registered patient <ID>`; validation failures print the reason (D7) and exit 1.
- `list` prints a table: ID, label, sessions, last session date.
- `delete` prompts `Delete patient <ID> and N sessions? [y/N]` unless `--yes`; prints counts
  removed. `unassigned` → exit 1 `The built-in 'unassigned' patient cannot be deleted`.

## Sessions

```text
python interfaces/cli.py sessions list [--patient <ID>] [--json]
python interfaces/cli.py sessions show <SESSION_ID> [--json]
```

- `list` is newest first: session ID, date/time, patient, source, exercises, reps, avg form.
- `show` prints the header, then the event log one line per event with units
  (`ROM 78.4°`, `form 95/100`, `2.1 s`), then the summary and status. Interrupted sessions
  print `STATUS: interrupted` (US3 scenario 3).

## Export

```text
python interfaces/cli.py export <SESSION_ID> --format {pta_log,observation_json,csv_report,text_log,all} [--out DIR]
```

- Default `--out exports/`. Prints each path written. File names:
  `{patient_id}_{YYYYMMDD_HHMMSS}.{txt|json|csv|log}`; `text_log` may write several
  `..._01.log`, `..._02.log` files (50-line cap, legacy behaviour).

## Import

```text
python interfaces/cli.py import-legacy [--sessions-dir sessions] [--obs-dir observation_logs] [--dry-run]
```

- Prints one line per file: `imported → session <id>`, `duplicate (already imported)`,
  `duplicate (same session found in both folders)`, or `malformed: <reason>`; ends with totals.
- `--dry-run` reports without writing.

## Database location

- Default `data/ptassist.db` relative to the repo root; override with `PTASSIST_DB=<path>`
  environment variable (used by tests and by users who keep data elsewhere).
