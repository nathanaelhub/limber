# Tasks: Plans of Care, Appointments, and Photo and Document Attachments (017)

Built test-first. Each task names the tests that pin it. T001–T008 are the backend and the patient API;
T009–T012 are the screens, built from the Claude Design export in `design/limber-export/`.

- [x] T001 Schema v15: `plans_of_care`; `plan_id` on messages, sessions, entries, media, program and
      questionnaire assignments; `appointments`; `attachments`; `clinic_settings`. Each patient's existing
      records go into one active "Plan of care", keeping message order and read state.
      Tests: `tests/test_ptlog_store_v14.py` (FR-005; US1 scenario 1; US2 scenario 2) and the v9–v13 upgrade tests.
- [x] T002 Plans: open (title, diagnosis, diagnosis visible to patient defaults to no, start); edit; status
      active → completed → archived; a new patient starts with one plan; plans go with the patient; caseload
      scoping. Tests: `tests/test_plans_of_care.py::TestPlans` (FR-001).
- [x] T003 Archived plans are read-only in the data layer: `PlanArchived` on every plan-scoped add, edit,
      or delete. Reading, marking read, and the patient deleting their own upload stay allowed.
      Tests: `TestArchivedPlansAreReadOnly` (FR-002; US1 scenario 2).
- [x] T004 Conversations per plan: send into one plan (the current plan when none is named); unread per
      plan rolls up to the patient; reading one plan marks only that plan.
      Tests: `TestConversationsPerPlan` (US2 scenario 1).
- [x] T005 Appointments: stored in UTC and shown in the clinic time zone (a setting, default America/Chicago);
      a reschedule request is flagged; a new time or a decline clears it; cancelled ones stay visible; an
      unmarked past one is "past". Tests: `tests/test_appointments.py` (FR-004; US4 scenarios 1–3).
- [x] T006 Attachments: up to 4 photos (JPEG, PNG, HEIC; 15 MB each) or 1 PDF (20 MB). Type is sniffed from
      the bytes. Photos are re-encoded on the host, which removes EXIF/GPS and PNG text and keeps orientation.
      Files are stored privately under `media/<patient>/attachments/`, deleted with the patient, ignored by the
      clip reconciler, and deleted by retention 1 year after archive. Tests: `tests/test_attachments.py`
      (FR-003; US3 scenarios 1–3).
- [x] T007 Portal API, all with origin checks:
      - `GET /api/plans`
      - `GET`/`POST /api/plans/{id}/messages` (JSON, or multipart with `files`)
      - `GET`/`DELETE /api/attachments/{id}`
      - `GET /api/appointments`
      - `POST /api/appointments/{id}/reschedule`

      Every write route answers 409 with `archived: true` for an archived plan. This covers messages,
      check-ins, diary, uploads, and reschedule, and a live session is refused with `plan_archived`.
      Tests: `tests/test_portal_plans_http.py` (SC-002).
- [x] T008 `media retention` on the command line also applies attachment retention.
      Tests: `tests/test_attachments.py::test_retention_deletes_a_year_after_archiving`.
- [x] T009 Patient pages:
      - Messages: a plan switcher with unread counts, a thread per plan with date dividers and "Seen" on the
        patient's own messages, photo thumbnails that open full size, PDF chips, and an add sheet (take a
        photo on phones, choose photos, choose a PDF). The tray shows "N of 4 photos" with a remove button on
        each and keeps the one-PDF rule. An ended plan shows a read-only panel with a link to the active plan.
      - Today: plan cards and the next visit.
      - Visits (`/visits`): an upcoming and earlier list, a month view, and a reschedule sheet with sending
        and request-sent states.
      - Navigation: five items on every page, a bottom tab bar on phones. `/visits` is in the installed app.

      Tests: `tests/test_portal_screens_017.py` and `tests/test_portal_viewmodels.py::TestTodayView`.
- [x] T010 Therapist app:
      - Inbox: a Plans column with unread per plan, a "Plan of care" picker, photos as thumbnails, PDFs as
        downloads, attaching photos or a PDF to a reply into the chosen plan, an archived plan read-only, and
        reschedule requests flagged.
      - Patient page: open, edit, complete, reopen, and archive plans, with a diagnosis and "show to
        patient" toggle. Visits: add, change the time, decline a request with a reply, and cancel.
      - Streamlit theme from the design.

      Tests: `tests/test_app_plans.py`.
- [x] T011 Demo record (`scripts/seed_demo.py`):
      - P-021 gets a second plan ("Left shoulder", diagnosis shown) and a photo in the hip plan.
      - P-017 gets an archived "Left ankle sprain" plan.
      - Visits include one with a reschedule request, a cancelled one, and a past one.
- [x] T012 Browser walk.
      - Phone, 390px: as P-021 with a code and as `patient017`, larger text plus higher contrast, and the
        768px top bar.
      - Laptop, 1280px: the therapist inbox and the patient page.

      Screenshots are in the session scratchpad.

## Dependencies (Principle V)

None added. Photos are cleaned with Pillow, already a dependency (`requirements.txt`). HEIC is read only if
the optional `pillow-heif` plug-in is installed. Without it, a HEIC photo is refused with a plain message
(see the spec's Deviations).
