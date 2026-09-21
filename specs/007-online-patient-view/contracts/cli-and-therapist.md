# Contract: therapist controls

## Command line

```text
portal code create P-017 [--days 90]     # prints the code once, the expiry, and the reminder below
portal code list                         # patient, state (active until / expired / revoked / none), last used
portal code revoke P-017                 # also signs the patient out and ends a running home session
portal audit [--patient P-017] [--limit 50]
portal serve [--host 127.0.0.1] [--port 8600] [--public-origin https://name.example]...
             [--trust-proxy] [--certfile F --keyfile F] [--insecure-http]
```

- `create` prints: `Access code for P-017: 7K3M-QX2P-9RTD (valid until 2026-12-20). It is shown
  only once. For demo and study use only.` Refused for the built-in patient, discharged patients,
  and unknown patients (exit 1).
- `serve` on a host other than loopback without a certificate exits 1 unless `--insecure-http` is
  given, and then warns that cameras will not work. When the pose assets are missing it prints
  `Run: python scripts/fetch_portal_assets.py` and still starts.
- Audit lines: `2026-09-21 09:15 | P-017 | login_ok | client 3fa9c1d2e4b7a680`. Never a code or an
  address.

## Therapist web app

- Patients page, per patient, "Home access": state, expiry, last use; "Issue code" (shows the code
  once in a copyable box with the study-use reminder) and "Revoke".
- Wherever sessions are listed or compared (Sessions, Review trends, compare, session review,
  exports, roster details), each session shows where it was recorded: `clinic` or `home`.
- Review trends and flags show clinic and home series separately; a flag's evidence says which.
- Comparing a home session with a clinic session is refused with an explanation.

## Exports

Review report and CSV gain the origin per session row; trend blocks and flags are per origin.
The four legacy per-session formats are unchanged.
