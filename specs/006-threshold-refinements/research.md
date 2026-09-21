# Research: Threshold Refinements

- **D1 Exercise identity**: the display name stored on exercise sets (`exercise_name`), because
  measures, trends, flags, and goals are already keyed by it.
- **D2 Exercise-level keys**: `EXERCISE_KEYS` = all registry keys except `practice_gap` and
  `adherence`; enforced by `validate_exercise_key`.
- **D3 Resolution**: `resolve(patient, installation, exercise=None)`; layers exercise → patient →
  installation → default. `Thresholds.defaults()` and two-layer calls are unchanged, so FR-009
  holds by construction.
- **D4 History write**: `_log_change(scope, patient_id, exercise_name, key, old, new)` called by
  every setter/resetter after comparing with the stored value; no row when old == new; bulk
  operations log one row per key removed. Same transaction as the change.
- **D5 History read**: patient history = rows for the patient (scopes patient, exercise) plus all
  installation rows; installation history = installation rows. Newest first by id.
- **D6 Bulk load for roster**: `effective_thresholds_by_exercise_all()` returns
  `{patient_id: {exercise_name: Thresholds}}` from one query; tracker passes it down.
- **D7 CSV**: the `thresholds_in_use` cell is computed per row from the row's exercise set.
