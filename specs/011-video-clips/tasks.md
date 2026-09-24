# Tasks: Video Clips and PT Review

- [x] T001 Branch; spec; plan; tasks
- [x] T002 [P] tests/fixtures/media.py (PyAV-generated mp4/h264, webm/vp8, mov/hevc, audio-only m4a, png renamed .mp4, html, truncated mp4, 70 s clip) and failing tests/test_media_probe.py: accept matrix, refusals with reasons, isolation (timeout and crash handled)
- [x] T003 Implement src/media/probe.py
- [x] T004 [P] Failing tests/test_portal_uploads.py + test_ptlog_store_v10.py: schema v10; upload create/part/finish (hash, size, probe, register); limits (open, count, bytes); expiry cleanup; list/delete/marker; retention; reconcile; cascade removes files; audit events
- [x] T005 Implement src/portal/uploads.py and store v10
- [x] T006 [P] Failing HTTP tests: routes, ownership 404s, octet-stream parts with Origin check, resume (missing parts), no-leak walk on media routes; today view carries clip counts
- [x] T007 Implement routes, clip.html/js
- [x] T008 [P] Failing tests: queue kind `new_uploads`, roster mark; AppTest for the tab (list, review, delete); backup/restore of media
- [x] T009 Implement tracker, app tab, backup, CLI `media`
- [x] T010 Docs (Update 13), DEPLOYMENT.md media notes, demo clip; Chrome run (fake camera clip recorded, uploaded in parts, played by the PT); record results; commit and merge
