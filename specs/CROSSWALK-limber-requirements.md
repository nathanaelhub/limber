# Crosswalk: the students' Limber requirements against this build

**Created**: 2026-10-29
**Source**: `constitution.md` in Lunatic-Labs/Limber (v1 scope, data model, V2 additions, LIM-15), read
2026-10-29. Our side: features 001–015 in this repository.

This build is our own implementation. It takes the students' *requirements*, not their code or UI.
Where both projects ask for the same thing, ours is listed as the existing home.

| # | Their requirement | Our build today | Gap | Lands in |
|---|-------------------|-----------------|-----|----------|
| 1 | Roles: patient, physician, administrator | Therapist (one shared password) and patient (device code) | No admin; one therapist only | **016** |
| 2 | Admin invites users (physicians, patients, admins); sees a user list | — | All of it | **016** |
| 3 | Onboarding from an invite link: name, password, accessible mode | Patient gets a code from the therapist | Invite link, account creation | **016** |
| 4 | Username + password, hashed | Therapist password (hashed); patient codes | Per-person accounts | **016** |
| 5 | Physician has many patients; patient has one physician | One caseload | Several therapists, each with a caseload | **016** |
| 6 | Accessibility preferences (LIM-15), reused by onboarding | Large tap targets, plain language | Stored per-person preference | **016** |
| 7 | Plan of care per episode: status active/completed/archived | Programs (exercises) per patient, no episode | Episode record with diagnosis and status | **017** |
| 8 | Messages tied to a plan of care | Messages (008) per patient | Group by plan; archived plan read-only | **017** |
| 9 | Attachments: photo, video, document, camera capture | Video clips (011), voice notes (014) | Photos and documents | **017** |
| 10 | Appointments: time, status, reschedule-request flag + note | — | All of it | **017** |
| 11 | Real-time chat | Messages with polling | Not planned: polling meets the need locally | — |
| 12 | Exercise schedule, progress graphs (their "future") | Programs, logs, review over time, thresholds (001–006) | Already ours | — |
| 13 | Motion capture (their "future") | Live session with pose tracking (004) | Already ours | — |
| 14 | Private physician notes (their "future") | Session notes are therapist-only | Already ours | — |
| 15 | Diary, questionnaires, voice notes | 012, 013, 014 | Ours, beyond their scope | — |
| 16 | (Ours) AI help for the therapist and patient | — | All of it | **018** |

## Where we deliberately differ

- **No email sending.** An admin invite produces a single-use link the admin copies and hands over. Nothing
  leaves the host, which Principle III requires; a mail service would be a separate networked feature.
- **Patient codes stay.** A patient can create a password account from an invite *or* keep using a
  therapist-issued device code. Some patients will not manage a password.
- **Polling, not Pusher.** The app runs on one host; a third-party push service is not needed.
- **AI processing needs a constitution amendment** (v1.3.0, drafted in 018), because it sends patient text
  to Anthropic.

## Order

016 first (everything else needs real accounts), then 017, then 018. 018 slice A (therapist assistant) can
start in parallel with 017, since it reads only data that already exists.
