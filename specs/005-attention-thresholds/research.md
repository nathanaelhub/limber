# Research: Configurable Attention Thresholds

No NEEDS CLARIFICATION remains.

## D1. One registry
- **Decision**: `thresholds.py` holds `THRESHOLDS: Dict[str, ThresholdDef]` in display order with
  keys `practice_gap`, `form_drop`, `rom_regression`, `rom_plateau`, `target_reps_sessions`,
  `partial_share`, `partial_rise`, `adherence`. The constants in `flags.py` are replaced by reads
  of the `Thresholds` argument; the window sizes stay constants there.
- **Rationale**: constitution V: one place for unit, meaning, default, range.

## D2. Storage shape
- **Decision**: two key-value tables, `patient_thresholds(patient_id, key, value)` and
  `installation_thresholds(key, value)`, with `CHECK (typeof(value) = 'integer')`; range checks
  live in `thresholds.validate()` because ranges differ per key.
- **Alternatives**: one wide row per patient (a migration for every new threshold); JSON column
  (no integrity).

## D3. Migration and the old settings
- **Decision**: v4 copies every `review_settings.gap_days` row to `patient_thresholds`
  (`practice_gap`) and a `tracker_settings.adherence_threshold` different from 60 to
  `installation_thresholds` (`adherence`). Old tables remain, unread. `get/set_gap_days` and
  `get/set_adherence_threshold` keep their signatures and delegate to the new tables, so existing
  CLI flags, web controls, and tests keep working (FR-009).
- **Alternatives**: dropping the old tables (breaks tests that assert the v2/v3 tables exist and
  gains nothing).

## D4. Resolution
- **Decision**: `resolve(patient_values, installation_values) -> Thresholds`; `Thresholds.value(key)`,
  `.origin(key)` in {"patient","installation","default"}, attribute-style accessors for the
  rules. `Thresholds.defaults()` is the argument default of every rule, which is what makes
  FR-010 hold by construction.

## D5. Evidence wording
- **Decision**: every threshold-driven flag's `values` dict gains `"threshold"` and its sentence
  ends with `(threshold N unit)`, as the practice-gap flag already does. The form rule's
  "each lower than the previous" branch has no threshold; it states the form-drop threshold only
  when the drop branch fired. FR-010's "apart from evidence wording" covers this.

## D6. Roster performance
- **Decision**: `store.effective_thresholds_all()` loads both tables once and returns a dict per
  patient; `tracker.roster()` and `queue()` use it instead of per-patient queries.

## D7. Interfaces
- **Decision**: CLI `review thresholds <patient>` (list), `review thresholds <patient> --set KEY=VALUE ...`,
  `--reset KEY ...`, `--reset-all`; `review thresholds --installation` with the same options and
  `--restore-defaults`. Web: a data table plus one number input per threshold inside the existing
  Review "Goals & settings" section, and an installation editor in the Tracker settings section.
