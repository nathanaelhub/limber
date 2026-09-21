# Tasks: Messages

Tests are REQUIRED and precede their implementation. Suite: `.venv/bin/python -m pytest tests`.

- [ ] T001 Branch `008-messages`; commit plan and tasks
- [ ] T002 [P] Failing tests in tests/test_messages.py: schema v8; off by default; enable/disable; send both ways with 1-2,000 characters; plain text kept exactly (markup, emoji, line breaks); privacy check reasons (name, date, record number, phone, email) raise `NeedsConfirmation` unless confirmed, and the confirmation is recorded; patient rate limit of 20 an hour; refused when messaging is off, the patient is discharged, or unknown; thread marks only the other side's messages read; inbox order, first line, unread counts, total; remove leaves a marker and hides the text; events recorded without text; cascade on patient delete and ID change
- [ ] T003 Implement schema v8 and store methods in src/ptlog/store.py, entities in src/ptlog/models.py, rules in src/portal/messages.py
- [ ] T004 [P] [US2] Failing tests in tests/test_portal_http.py: `GET/POST /api/messages` need a sign-in; disabled means `enabled: false` and 403 on send; send, warning (409 with reasons) and confirm; the thread never contains another patient's text; today view carries `messages.enabled` and `messages.unread`; the Messages page always shows the not-for-emergencies notice; the no-leak test covers the message routes
- [ ] T005 [US2] Implement the routes, `messages_view`, messages.html, messages.js, and the nav link
- [ ] T006 [P] [US1] Failing tests in tests/test_app_pages.py and tests/test_ptlog_tracker.py: Inbox lists conversations with unread counts; opening a thread marks it read; reply is stored; enable/disable; remove a message; sidebar unread count; roster `unread_messages`; queue kind `unread_messages`
- [ ] T007 [US1] Implement the Inbox page, sidebar count, Patients-page toggle in interfaces/app.py, roster and queue in src/ptlog/tracker.py and views, and the `messages` CLI group
- [ ] T008 [US3] Thread context (latest session summary and open flags beside the thread); test and implement
- [ ] T009 Seed demo conversations; docs/UPDATES.md (Update 10), README; scripted two-sided conversation in Chrome; record results; commit and merge
