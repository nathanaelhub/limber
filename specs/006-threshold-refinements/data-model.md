# Data Model: Threshold Refinements (schema v5)

```sql
CREATE TABLE IF NOT EXISTS exercise_thresholds (
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    exercise_name TEXT NOT NULL,
    key           TEXT NOT NULL,
    value         INTEGER NOT NULL CHECK (typeof(value) = 'integer'),
    PRIMARY KEY (patient_id, exercise_name, key)
);
CREATE TABLE IF NOT EXISTS threshold_changes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at    TEXT NOT NULL,
    scope         TEXT NOT NULL CHECK (scope IN ('patient', 'exercise', 'installation')),
    patient_id    TEXT REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    exercise_name TEXT,
    key           TEXT NOT NULL,
    old_value     INTEGER,          -- NULL = no stored value (inherited)
    new_value     INTEGER           -- NULL = stored value removed
);
CREATE INDEX IF NOT EXISTS idx_threshold_changes_patient ON threshold_changes(patient_id, id);
```

`ThresholdChange(id, changed_at, scope, patient_id, exercise_name, key, old_value, new_value)`.
