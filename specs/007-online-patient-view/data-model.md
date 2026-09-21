# Data Model: Online Patient View (schema v6)

## New tables (forward-only migration; nothing existing changes)

```sql
CREATE TABLE IF NOT EXISTS portal_access (
    patient_id    TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    code_lookup   TEXT NOT NULL UNIQUE,      -- HMAC-SHA256(server key, normalised code), hex
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    revoked_at    TEXT,
    last_used_at  TEXT
);
CREATE TABLE IF NOT EXISTS portal_sessions (
    token_hash    TEXT PRIMARY KEY,          -- SHA-256 of the cookie token, hex
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,
    created_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portal_sessions_patient ON portal_sessions(patient_id);
CREATE TABLE IF NOT EXISTS portal_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    patient_id  TEXT REFERENCES patients(id) ON DELETE CASCADE ON UPDATE CASCADE,  -- NULL for unknown codes
    event       TEXT NOT NULL CHECK (event IN ('code_created','code_revoked','login_ok','login_failed',
                 'locked_out','logout','live_start','live_end','live_interrupted','live_refused')),
    client      TEXT,                        -- first 16 hex of HMAC(server key, address); never the address
    detail      TEXT                         -- short fixed vocabulary, e.g. 'expired', 'second_device', 'low_rate'
);
CREATE INDEX IF NOT EXISTS idx_portal_audit_patient ON portal_audit(patient_id, id);
```

One row per patient in `portal_access`: issuing a new code replaces the row (the old code stops
working) and deletes the patient's `portal_sessions`.

## Entities (code)

- `AccessStatus(patient_id, state, created_at, expires_at, revoked_at, last_used_at)` with `state`
  in `none | active | expired | revoked`.
- `PortalSignIn(patient_id, created_at, last_seen_at, expires_at)`.
- `AuditEntry(id, at, patient_id, event, client, detail)`.
- `PortalError(PTLogError)` with `AccessDenied`, `LockedOut`, `FrameError`, `LiveRefused`.

## Rules

- Code: 12 Crockford base32 characters; normalise before hashing; default lifetime 90 days
  (1-365 allowed); refused for the built-in patient and for discharged patients; a discharged
  patient's existing code is refused at sign-in.
- Sign-in: idle 30 minutes, absolute 12 hours, at most three per patient (oldest removed).
- Home session: an ordinary `sessions` row with `source = 'webcam'`, `source_ref = 'home'`, and
  `source_extras = {"origin": "portal", "pose_model": "movenet-lightning-4", "fps_nominal": 15,
  "pid": ...}`; at the end `fps_observed`, `frames_dropped`, and `low_rate` are written to the
  access history detail (the session row's extras are not rewritten).
- **Capture origin** (derived, not stored): `home` when `source_extras.origin == "portal"`, else
  `clinic`. `SessionMeasure` gains `origin`. Comparisons across sessions use one origin at a time.
- Running sessions: `start_session(patient)` supersedes only that patient's running sessions.

## Message and view shapes

See [contracts/http-api.md](contracts/http-api.md) and [contracts/websocket.md](contracts/websocket.md).
