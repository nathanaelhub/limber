# Tasks: Accounts, Roles, Invitations, and Accessibility Preferences (016)

Built test-first. Each task names the tests that pin it.

- [x] T001 Schema v14: accounts, caseloads, invitations, account audit; v7 password becomes the first
      admin-therapist; patient preferences column — `tests/test_accounts.py::TestSchema`, upgrade tests v9–v13
- [x] T002 Account rules: usernames, names, passwords, sign-in limits per client and per username, disable,
      last admin — `TestAccounts` (US1, FR-001–003)
- [x] T003 Invitations and onboarding: single use, 7 days, revoke, failed onboarding keeps the link, patient
      invites join a caseload — `TestInvitations` (US1, US2)
- [x] T004 Caseloads in the record: a restricted store hides other therapists' patients from every
      cross-patient read; reassignment; new patients join the adding therapist — `TestCaseloads` (US3, FR-004)
- [x] T005 Preferences for staff and patients; CSS classes — `TestPreferences` (US4)
- [x] T006 Therapist door per account; patients' password door — `TestStaffSignIn`, `TestPatientPasswordSignIn`
- [x] T007 Portal: username at both doors, invite page and API, settings page and API, classes on first
      render — `tests/test_portal_accounts_http.py`
- [x] T008 Therapist app: sign in as a person, caseload-only patient picker and pages, People (admins),
      My settings — `tests/test_app_pages.py` (feature 016 section)
- [x] T009 Command line: `portal accounts create-admin`, `portal accounts list` — `tests/test_cli_portal.py`
- [x] T010 Demo record: admin, two therapists with separate caseloads, a patient account — `scripts/seed_demo.py`
- [x] T011 Browser walk (phone for the invite and settings, laptop for the therapist door), 2026-10-30
