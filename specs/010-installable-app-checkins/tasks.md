# Tasks: Installable App and Pain Check-ins

Tests are REQUIRED and precede their implementation. Suite: `.venv/bin/python -m pytest tests`.

- [x] T001 Constitution 1.2.0; branch; commit spec, plan, tasks
- [x] T002 [P] Failing tests in tests/test_ptlog_entries.py: registry fields, ranges, definitions; `validate` accepts a good check-in, rejects out-of-range pain, unknown area, bad levels, note over 500, future or stale recorded_at (marked and replaced); pain series helper
- [x] T003 [P] Failing tests in tests/test_ptlog_store_v9.py: v8 record upgrades to v9 keeping every row in every table (counts before and after, foreign keys on); entries add (idempotent on client_id), list, note removal, cascade on delete and ID change; audit events `entry_stored`, `entry_note_removed`
- [x] T004 Implement src/ptlog/entries.py, schema v9 and methods in src/ptlog/store.py, models
- [x] T005 [P] Failing tests in tests/test_ptlog_flags.py and test_ptlog_thresholds.py: `pain_rise`/`pain_high` in the registry, patient-level (not in EXERCISE_KEYS); rules fire with stated thresholds; `flags_for` includes them; queue and roster mark; with no entries every result unchanged
- [x] T006 Implement thresholds, flags, review, tracker changes
- [x] T007 [P] Failing tests in tests/test_portal_access.py: a device sign-in lasts 30 days regardless of idle, three per patient, ends on revoke or reissue; the non-device sign-in keeps today's limits
- [x] T008 Implement in src/portal/access.py and the login route (`device: true`)
- [x] T009 [P] Failing tests in tests/test_portal_pwa.py and test_portal_http.py: manifest and sw.js served at the root with correct types and headers; precache list contains only existing files and never /api; `/api/entries` POST (validation, warn 409 and confirm, idempotent client_id, discharged refused) and GET (own entries only); today view carries the check-in prompt; progress carries pain; no-leak walk extended
- [x] T010 Implement src/portal/pwa.py, routes, checkin.html/js, sw.js, install hint, offline snapshot and queue in portal.js, pain on progress.js
- [x] T011 [P] Failing AppTest: Review "From the patient" tab shows the trend, table, definitions, note removal
- [x] T012 Implement in interfaces/app.py; seed demo check-ins; docs (Update 12), README; suite; Chrome phone-emulation run (install hint, offline shell, queued check-in replay); record results; commit and merge
