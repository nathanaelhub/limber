# Implementation Plan: Video Clips and PT Review

**Branch**: `011-video-clips` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

## Summary

Chunked uploads through the patient service into `data/media/<patient>/`, a PyAV probe run in a
subprocess with a timeout that decides the type, `media` and `media_uploads` tables (schema v10),
patient list/play/delete routes, a clip page with camera capture and resumable upload, PT playback
and review in the "From the patient" tab, `new_uploads` in the queue and roster, a retention and
reconciliation command, and media in the encrypted backup and restore.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine | PASS | Untouched. |
| II. One record | PASS | `SessionStore` owns the media rows; files are referenced, never the source of truth; `delete_patient` removes files. |
| III. Privacy (1.2.0) | PASS | Notice before recording; pseudonymous paths; retention; patient delete; host-only processing; access history without captions or filenames. |
| IV. Test-first | PASS | Fixtures are generated with PyAV at test time; no binary committed. |
| V. Simplicity | PASS | PyAV is already installed; no new dependency. |

## Structure

```text
src/media/probe.py          # probe(path) -> MediaInfo; run_isolated(path, timeout) via subprocess
src/portal/uploads.py       # limits, upload lifecycle, finish (assemble, hash, probe, register), retention, reconcile
src/ptlog/store.py          # v10: media, media_uploads; audit events; delete cascade of files
interfaces/patient_portal.py# /api/uploads*, /api/media*, /clip page; permissions-policy unchanged (camera=(self))
interfaces/portal_static/   # clip.html, clip.js
interfaces/app.py           # From the patient: clips with st.video, review, delete
src/ptlog/tracker.py        # new_uploads queue kind, roster unreviewed_uploads
src/deploy/backup.py        # media pass, restore
interfaces/cli.py           # media list|retention|reconcile
```
