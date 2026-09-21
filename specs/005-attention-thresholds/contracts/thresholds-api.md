# Contract: thresholds API

```python
# src/ptlog/thresholds.py
THRESHOLDS: Dict[str, ThresholdDef]            # ordered
validate(key: str, value) -> int               # raises ThresholdValidationError
resolve(patient: Mapping[str,int] | None, installation: Mapping[str,int] | None) -> Thresholds
Thresholds.defaults() -> Thresholds
Thresholds.value(key) -> int ; .origin(key) -> "patient"|"installation"|"default"
Thresholds.overridden() -> List[str]          # keys whose origin is not "default"

# SessionStore
get_patient_thresholds(patient_id) -> Dict[str,int]          set_patient_threshold(patient_id, key, value) -> int
reset_patient_threshold(patient_id, key) -> bool              reset_patient_thresholds(patient_id) -> int
get_installation_thresholds() -> Dict[str,int]                set_installation_threshold(key, value) -> int
reset_installation_threshold(key) -> bool                     restore_builtin_thresholds() -> int
effective_thresholds(patient_id) -> Thresholds                effective_thresholds_all() -> Dict[str, Thresholds]
# unchanged signatures, now delegating: get_gap_days, set_gap_days, get_adherence_threshold, set_adherence_threshold

# flags.py
evaluate(series_by_exercise, goals, session_starts, thresholds_or_gap_days, now) -> FlagResult
#   accepts a Thresholds, or an int gap for backward compatibility (built-in defaults for the rest)
```

Unknown patient → `PatientNotFoundError`. All setters validate before writing.
