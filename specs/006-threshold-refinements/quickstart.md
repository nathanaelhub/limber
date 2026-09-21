# Quickstart: Threshold Refinements

1. `.venv/bin/python -m pytest tests -q` → green.
2. On a temp database with a 6° ROM drop in two exercises:
   `review thresholds P-017 --exercise "Knee Extension" --set rom_regression=5` →
   `review flags P-017` flags Knee Extension only, stating `threshold 5 degrees`.
3. `review thresholds P-017 --exercise "Knee Extension" --set adherence=50` → exit 1, message says
   adherence applies to the whole patient.
4. `review thresholds P-017 --history` → entries newest first; saving the same value again adds none.
5. `review export P-017 --format report` → thresholds section names the exercise override.
6. Web: Review → Goals & settings → Applies to: Knee Extension → save → Change history shows it.
