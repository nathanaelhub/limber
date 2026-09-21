# Tasks: Cloud Deployment

- [X] T001 Branch; commit plan and tasks
- [X] T002 [P] Failing tests in tests/test_deploy_preflight.py: each check passes and fails with a plain reason (no therapist password; no server key; record directory not writable; pose assets missing; public origin missing or not https; therapist address not under the public origin); `init` creates the key (0600), sets the password from a secret file, and never prints it; preflight exit codes through the CLI
- [X] T003 Implement src/deploy/preflight.py and `deploy preflight|init` in interfaces/cli.py
- [X] T004 [P] Failing tests in tests/test_deploy_backup.py: backup of a live record with a writer open; the file is not readable as SQLite and contains no patient ID; restore round-trip equals the source; wrong key refused; retention keeps 14; verify detects a corrupted file; restore refuses to overwrite without `--force`
- [X] T005 Implement src/deploy/backup.py and `deploy backup|restore`; pin `cryptography` in requirements.txt
- [X] T006 [P] Failing test: `/api/health` reports `record: ok` and returns 503 when the record cannot be written
- [X] T007 Implement the health check
- [X] T008 [P] Static tests in tests/test_deploy_files.py: the Dockerfile runs as a non-root user, fetches pose assets at build time, bakes in no secret; compose exposes only the proxy's 80/443, mounts one volume, runs one replica, has a health check; the Caddyfile routes `/therapist*` to the therapist app and everything else to the patient service; the entrypoint runs preflight before starting anything
- [X] T009 Write deploy/Dockerfile, compose.yaml, Caddyfile, entrypoint.sh, limber.env.example
- [X] T010 Run the therapist app under `/therapist` locally with the front page handing over to it; record the result
- [X] T011 docs/DEPLOYMENT.md runbook; docs/UPDATES.md (Update 11); README; record what was and was not verified; commit and merge
