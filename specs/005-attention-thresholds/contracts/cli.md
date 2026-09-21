# Contract: command line

```text
review thresholds P-017
review thresholds P-017 --set rom_regression=5 form_drop=8
review thresholds P-017 --reset rom_regression
review thresholds P-017 --reset-all
review thresholds --installation [--set KEY=VALUE ...] [--reset KEY ...] [--restore-defaults]
```

Listing prints one line per threshold:
`ROM regression: 5 degrees (patient; default 10) - <meaning>`; origins print as `patient`,
`installation`, or `default`. Invalid input exits 1 (the command line's existing code for a rejected value) with the range message and changes nothing
(all `--set` pairs are validated before any is written). Existing `review settings --gap-days`
and `tracker settings --adherence-threshold` keep working. `tracker adherence P-017` prints
`Attention threshold: 50% (patient)`.
