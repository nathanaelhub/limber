# Quickstart: Configurable Attention Thresholds

1. `.venv/bin/python -m pytest tests -q` → green.
2. Upgrade check: copy an existing v3 `data/ptassist.db` to a temp path, set `PTASSIST_DB`, run
   `python interfaces/cli.py review thresholds <patient with a gap override>` → the gap value
   shows origin `patient`; `tracker settings` shows the previous adherence value.
3. `review flags P-017` → note the flags; `review thresholds P-017 --set rom_regression=5` →
   `review flags P-017` shows a regression flag stating `threshold 5 degrees` when the data has a
   5-9° drop; `--reset rom_regression` removes it.
4. `review thresholds P-017 --set form_drop=0` → exit code 1, message with `1-50 points`.
5. `review thresholds --installation --set adherence=50`, `tracker roster` → attention changes for
   patients without overrides; `--restore-defaults` reverts.
6. `review export P-017 --format report` → thresholds section marks overrides.
7. Web: Review → Goals & settings → change a threshold → Flags section updates.

Done when steps 1-6 pass and `docs/UPDATES.md` has an entry.
