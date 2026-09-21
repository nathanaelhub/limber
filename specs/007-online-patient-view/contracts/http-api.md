# Contract: patient service HTTP API

All API responses are JSON with `Cache-Control: no-store`. No request carries a patient ID. POSTs
need `Content-Type: application/json` and an allowed `Origin`. Errors: `{"error": "<plain message>"}`.

| Route | Auth | Response |
|-------|------|----------|
| `GET /` `/today` `/session` `/progress` | pages; the three inner pages redirect to `/` when not signed in | HTML from `interfaces/portal_static/` |
| `POST /api/login` `{"code": "XXXX-XXXX-XXXX"}` | none | 200 `{"patient_id": "P-017"}` and the sign-in cookie; 401 generic message for wrong, expired, revoked, discharged; 429 with `retry_after_seconds` when locked out |
| `POST /api/logout` | cookie | 200 `{}`; cookie cleared |
| `GET /api/today` | cookie | see below |
| `GET /api/progress` | cookie | see below |
| `GET /api/health` | none | `{"ok": true, "pose_assets": true|false}` |

`GET /api/today`:

```json
{"patient_id": "P-017", "date": "2026-09-21",
 "program": {"name": "Knee Rehabilitation", "sessions_per_week": 3},
 "exercises": [{"key": "knee_extension", "name": "Knee Extension", "target_reps": 10, "done_today": false}],
 "week": {"done": 2, "planned": 3}, "streak_weeks": 3,
 "message": null}
```

`program` is null and `message` is "Your therapist has not assigned a program yet." when there is
no active assignment.

`GET /api/progress`:

```json
{"patient_id": "P-017",
 "definitions": {"avg_rom": {"name": "Range of motion", "unit": "degrees", "meaning": "..."},
                 "avg_form": {"name": "Form score", "unit": "0-100", "meaning": "..."}},
 "exercises": [{"name": "Knee Extension",
   "goal": {"target_rom": 95.0, "sentence": "86° of your 95° goal", "percent": 72},
   "series": {"home": [{"date": "2026-09-19", "avg_rom": 84.1, "avg_form": 88.0, "reps": 10}],
              "clinic": [...]},
   "change": {"home": {"avg_rom": 3.1, "avg_form": 1.5}, "clinic": null},
   "message": null}]}
```

`change` is null and `message` says more sessions are needed when an origin has fewer than two
sessions. Goal progress uses the origin of the latest session and says which.

**Forbidden in every response** (tested): the keys `flags`, `flag`, `notes`, `review`, `next_step`,
`threshold`, `thresholds`, `label`, and any patient ID other than the signed-in one.

Headers on every response: the content security policy and the other headers in research D5.
