# Data Model: Configurable Attention Thresholds

## Schema v4 (forward-only)

```sql
CREATE TABLE IF NOT EXISTS patient_thresholds (
    patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    key        TEXT NOT NULL,
    value      INTEGER NOT NULL CHECK (typeof(value) = 'integer'),
    PRIMARY KEY (patient_id, key)
);
CREATE TABLE IF NOT EXISTS installation_thresholds (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL CHECK (typeof(value) = 'integer')
);
INSERT OR IGNORE INTO patient_thresholds (patient_id, key, value)
    SELECT patient_id, 'practice_gap', gap_days FROM review_settings;
INSERT OR IGNORE INTO installation_thresholds (key, value)
    SELECT 'adherence', adherence_threshold FROM tracker_settings WHERE adherence_threshold <> 60;
```

## Registry (code, not stored)

| key | name | unit | default | range | meaning |
|-----|------|------|---------|-------|---------|
| practice_gap | Practice gap | days | 7 | 1-90 | Flag when more than this many days pass between sessions or since the last one |
| form_drop | Form drop | points | 10 | 1-50 | Flag when the latest average form score is at least this far below the best of the other three recent sessions |
| rom_regression | ROM regression | degrees | 10 | 1-60 | Flag when the latest average ROM is at least this far below the best of the previous three sessions |
| rom_plateau | ROM plateau | degrees | 3 | 1-30 | Flag when ROM changed by less than this over four sessions while below the goal |
| target_reps_sessions | Sessions below target | sessions | 3 | 2-10 | Flag when this many consecutive sessions ended below target reps |
| partial_share | Partial-rep share | percent | 25 | 1-100 | Partial-rep flag needs the latest share to be at least this |
| partial_rise | Partial-rep rise | percentage points | 10 | 1-100 | and at least this far above the mean of the previous three sessions |
| adherence | Adherence | percent | 60 | 1-100 | Mark the patient for attention when adherence is below this |

## Entities

- `ThresholdDef(key, name, unit, meaning, default, minimum, maximum)`.
- `Thresholds(values: Dict[str,int], origins: Dict[str,str])`: complete for all eight keys.
- `ThresholdValidationError(PTLogError)`: unknown key, not a whole number, out of range; message
  states the allowed range and unit.

## Rules

- Effective value: patient override → installation value → built-in default.
- Unknown keys found in the tables (from a newer version) are ignored on read.
- Deleting a patient removes overrides; renaming moves them (foreign key actions).
