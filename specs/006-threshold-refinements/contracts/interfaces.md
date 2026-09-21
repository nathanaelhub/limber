# Contract: interfaces

```text
review thresholds P-017 --exercise "Knee Extension"                 # list for that exercise
review thresholds P-017 --exercise "Knee Extension" --set rom_regression=5
review thresholds P-017 --exercise "Knee Extension" --reset rom_regression | --reset-all
review thresholds P-017 --history          review thresholds --installation --history
```

Exercise listing prints the six exercise-level thresholds; origin `exercise` shows
`(exercise; default <patient's effective value>)`. History lines:
`2026-09-21 09:15 | Knee Extension | ROM regression: default → 5 degrees`, scope shown as the
exercise name, `patient`, or `installation`. `--exercise` with `--installation` is rejected.

Web: the Review thresholds editor gains a "Applies to" selector (Whole patient, then the
patient's exercises); a "Change history" expander under it; Tracker → Settings gets the
installation history expander.

Report: after the eight lines (or the built-in-defaults sentence), one line per exercise override:
`Knee Extension: ROM regression 5 degrees (exercise override)`. CSV cell marks `(exercise)`.
