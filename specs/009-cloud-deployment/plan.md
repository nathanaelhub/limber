# Implementation Plan: Cloud Deployment

**Branch**: `009-cloud-deployment` | **Date**: 2026-09-21 | **Spec**: [spec.md](spec.md)

## Summary

Provider-neutral: one application image (patient service on 8600, therapist app on 8501 under the
path `/therapist`), a Caddy reverse proxy that obtains the certificate and is the only thing exposed,
and one persistent volume holding the record, the server key, exports, and backups. Python code added
here is small and testable without a container: a start-up check that refuses unsafe configurations,
a first-boot initialiser, an encrypted nightly backup with retention and a restore, and a health check
that proves the record is readable and writable. **No cloud resource is created by this feature**; the
owner's account and go-ahead are needed for that, and Docker is not installed on the development
machine, so the image itself has not been built or run here.

## Technical Context

Python 3.13; `cryptography` (already installed through aiortc) becomes a direct, pinned dependency for
backup encryption (Fernet). Container: `python:3.13-slim`, CPU-only torch. Proxy: Caddy 2. Tests:
pytest for `src/deploy/` and the CLI; the container files are checked by static tests only.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine | PASS | Untouched. The clinic's camera features stay on the clinic machine (owner decision). |
| II. One record | PASS | Still one SQLite file and one writer; exactly one instance runs; backups use SQLite's online backup. |
| III. Privacy (1.1.0) | PASS with a recorded limit | Hosting places the record with a provider. Study participants only until a compliance review approves provider, agreement, and procedures (spec FR-010). Logs carry no codes, passwords, tokens, or addresses. |
| IV. Test-first | PASS | Start-up check, initialiser, backup, restore, and health are test-first. |
| V. Simplicity | PASS with tracking | One direct dependency promoted (`cryptography`), justified below. |

## Complexity Tracking

| Item | Why | Simpler alternative rejected because |
|------|-----|--------------------------------------|
| `cryptography` as a direct dependency | Backups leave the volume's trust boundary and must be encrypted (FR-005) | The standard library has no authenticated encryption; relying only on provider disk encryption would leave copied backup files readable |
| Two processes in one container | One volume, one writer, one thing to deploy | Two containers sharing a SQLite file over a network volume risks corruption |

## Structure

```text
src/deploy/preflight.py     # checks: therapist password, server key, record writable, pose assets, https origin
src/deploy/backup.py        # online backup -> Fernet-encrypted file, retention, restore, verify
interfaces/cli.py           # deploy preflight | init | backup | restore
interfaces/patient_portal.py# /api/health proves read and write
deploy/Dockerfile  deploy/compose.yaml  deploy/Caddyfile  deploy/entrypoint.sh  deploy/limber.env.example
docs/DEPLOYMENT.md          # runbook: deploy, roll back, rotate key, reset password, backup, restore, offline
```
