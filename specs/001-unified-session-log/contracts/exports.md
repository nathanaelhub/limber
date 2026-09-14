# Contract: Export formats (legacy parity)

**Feature**: 001-unified-session-log. Each format below is what the retired writer produced;
the export MUST reproduce it byte for byte for the same event sequence (FR-022, SC-005).
Golden files in `tests/fixtures/golden/` are the executable form of this contract.

## 1. PTA-Log pipe-delimited text (`pta_log`, `.txt`) — from `PTARawLogger`

Header block (12 lines, then a `************` separator):

```text
PTA Observation Log
PTA-Log-NNNN.txt
Version: 1.00
Start time: YYYY:MM:DD:HH:MM:SS:sss

Timestamp | Message Type | Message Text | [Data CSV of key=value pairs]

Timestamp is in YYYY:MM:DD:HH:MM:SS:sss format
Message Types are: SYSTEM, LOG, ERROR
Fields are separated by '|' character
Fields marked with [] are optional
************
```

Line format: `TS | TYPE | "Message" | data` where the join is `" |"` between parts and each
part after the timestamp is prefixed with one space (legacy: `" |".join([ts, " TYPE ", ' "msg"', " data"])`).

Lines, in order:

| Moment | Type | Message | Data |
|--------|------|---------|------|
| start | SYSTEM | `Camera Detected.` | |
| start | SYSTEM | `System started successfully. Source: {webcam\|video}` | |
| start | LOG | `{exercise} exercise selected` | `min=0.0, max=0.0, angle=0.0, state=INIT, count=0` |
| each frame sample | LOG | `Observing {exercise}` | `min={down_angle:.1f}, max={up_angle:.1f}, angle={angle:.1f}, state={STATE}, count={n}` |
| rep | LOG | `Rep Completed` | `exercise="{exercise}", repCount={n}` |
| partial | LOG | `Partial Rep` | `exercise="{exercise}", rom={rom:.1f}, reason="{reason}"` |
| switch | LOG | `Exercise Changed` | `from="{a}", to="{b}"` |
| reset | LOG | `Counter Reset` | `exercise="{exercise}", repCountAtReset={n}` |
| end | LOG | `Session Summary` | `totalReps={n}, avgFormScore={x:.1f}, avgRom={y:.1f}` |
| end | SYSTEM | `System halted.` | |

`NNNN` is the session's 1-based ordinal among the patient's sessions, zero-padded to 4.
Interrupted sessions end with the Session Summary line computed from events, followed by an
`ERROR | "Session interrupted"` line and then `System halted.`. Form events are not part of
this format (the legacy writer never received them).

## 2. Observation JSON (`observation_json`, `.json`) — from `ObservationLogger`

Top level keys in order: `session_id` (`session_YYYY-MM-DD_HHMMSS` from start time),
`source`, `start_time`, `end_time`, `duration_seconds`, `initial_exercise`, `target_reps`,
`events`, `summary`. Serialized with `json.dumps(..., indent=2)`.

Events (`type`, `timestamp` first, then fields in this order):

- `session_start`: `exercise`, `target_reps`
- `rep`: `rep_number`, `exercise`, `rom`, `form_score`, `duration_seconds`, `min_angle`, `max_angle`
- `partial_rep`: `exercise`, `rom`, `min_angle`, `max_angle`, `duration_seconds`, `reason`
- `exercise_change`: `from_exercise`, `to_exercise`
- `reset`: `exercise`, `rep_count_at_reset`
- `session_end`: `total_reps`, `avg_form_score`, `avg_rom`, `duration_seconds`

Rounding: `rom`, `form_score`, `min_angle`, `max_angle`, `avg_*` to 1 decimal;
`duration_seconds` per rep to 2 decimals; session `duration_seconds` to 1 decimal.

`summary`: `total_reps`, `exercises_performed` (list of `{exercise, reps, avg_form_score,
avg_rom}` in first-seen order), `avg_form_score`, `avg_rom`, `warnings` (list). For an
interrupted session `end_time` is the last event time and `warnings` contains
`"Session interrupted"`.

`to_observation_dict()` returns this structure so `session_summary.generate_session_summary()`
consumes it unchanged.

## 3. CSV report (`csv_report`, `.csv`) — from `SessionTracker._save_csv`

Note: the per-rep CSV and the `session_summary`/`rep_details` JSON that `generate_session_report()`
wrote into `sessions/` are retired without an export (research D14); the importer still reads that
JSON shape.

```text
PT Session Report
Session ID,{session_id}
Patient ID,{patient_id}
Date,{YYYY-MM-DD}
Duration (min),{d:.1f}
Overall Form Score,{s:.1f}%

Exercise,Reps,Target,Form Score,ROM Min,ROM Max,ROM Range,Avg Rep Time
{name},{reps},{target},{f:.1f}%,{min:.1f}°,{max:.1f}°,{range:.1f}°,{t:.2f}s
...

Flags for Review            (block present only when non-empty)
{flag}

Therapist Notes             (block present only when non-empty)
{notes}
```

One exercise row per exercise set over reps not flagged out of range. `ROM Min`/`ROM Max` are
the set's minimum `min_angle` and maximum `max_angle`; `ROM Range` their difference; `Avg Rep
Time` mean rep duration. Flags reproduce the legacy rules (form score below 60; fewer than half
the target reps) plus `Session interrupted` when applicable. Notes: the patient's notes field
(no PHI by rule). Partial reps with reason `interrupted` never appear in the text log, because
the legacy loop replaced the tracker before its logging block could see them.
Written with `csv.writer` defaults (`\r\n` line endings).

## 4. Plain-text session log (`text_log`, `.log`) — from `SessionLogger`

Files of at most 50 lines: first line `# logfile created: YYYY-MM-DD HH:MM:SS`, continuation
files start with `# continued: ...`. Entry lines are `[HH:MM:SS] MESSAGE`:

| Moment | MESSAGE |
|--------|---------|
| start | `SESSION START \| Exercise: {name} \| Camera: {id} \| imgsz: {n} \| skip: {n}` (video: `Source: {file}`) |
| rep | `REP {n} \| ROM: {rom:.1f}° \| Form: {f:.0f}% \| Duration: {d:.1f}s \| Angle: {min:.0f}°-{max:.0f}°` |
| partial | `PARTIAL REP \| ROM: {rom:.1f}° \| Angle: {min:.0f}°-{max:.0f}° \| Reason: {reason}` |
| form | `FORM {STATUS} \| {message}` |
| switch | `SWITCH \| {a} -> {b}` |
| reset | `RESET \| Reps cleared at count={n}` |
| end | `SESSION END \| Total Reps: {n} \| Avg Form: {f:.0f}% \| Avg ROM: {r:.1f}°` (`SESSION INTERRUPTED \| …` for an interrupted session) |

`imgsz` and `skip` are read from the session's `source_extras` JSON (`camera_id`, `imgsz`,
`frame_skip`) so the start line can be reproduced; for video sessions the legacy writer was
not used, so the export writes the `Source:` variant.
