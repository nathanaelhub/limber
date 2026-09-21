# Feature Specification: Cloud Deployment

**Feature Branch**: `009-cloud-deployment`

**Created**: 2026-09-21

**Status**: Draft (not approved; nothing is built; no cloud resource has been created)

**Input**: User description: "Continue with the patient platform cloud infrastructure build."
This replaces the owner's earlier choice in feature 007 ("build now, run on one machine, decide
hosting later") with: run Limber on a cloud host so patients reach it from home without the
therapist's computer being on.

## What changes when Limber leaves the therapist's machine

| Today (one machine) | In the cloud |
|---------------------|--------------|
| The record is one SQLite file on the therapist's disk | The record lives on the host's persistent disk and must be backed up |
| The therapist app has no sign-in unless a password is set | A therapist password is mandatory; the app refuses to start without one |
| The patient service listens on this machine only | The patient front page is public on HTTPS; the therapist app is reachable only through the front page's sign-in |
| Pose detection in the clinic runs YOLO on the therapist's machine | The clinic's Live Session and video analysis keep running on the clinic machine, or the host needs enough CPU for them |
| Nothing is sent to a third party | The hosting provider stores the record; for real patients that requires a signed health-data agreement |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One Address for Everyone (Priority: P1)

Patients and therapists open one HTTPS address (for example `https://limber.example.org`), see the
Limber front page, and go through their door. The therapist's own computer can be off.

**Acceptance Scenarios**:

1. **Given** the deployed service, **Then** the front page loads over HTTPS with a valid
   certificate, and plain HTTP redirects to HTTPS.
2. **Given** a patient with a code, **Then** they sign in, see today's plan, and run a session with
   their phone's camera (browsers allow the camera because the page is on HTTPS).
3. **Given** the therapist door, **Then** the therapist reaches the therapist app only after
   signing in; the therapist app's own address is not reachable from the internet directly.
4. **Given** no therapist password is set, **Then** the deployment refuses to start.

### User Story 2 - The Record Survives (Priority: P1)

The record is on a persistent disk, backed up every night with 14 days kept, and a restore has
been rehearsed.

**Acceptance Scenarios**:

1. **Given** the host is restarted or redeployed, **Then** every patient, session, code, and
   setting is still there.
2. **Given** the nightly backup, **Then** a copy made with SQLite's online backup exists for each of
   the last 14 days, encrypted at rest.
3. **Given** a restore drill, **Then** the documented steps bring up a working copy from last
   night's backup in under 30 minutes.

### User Story 3 - Repeatable Deployment (Priority: P2)

Anyone with access can deploy the same thing from the repository: a container image, configuration
through environment variables, a health check, and a one-page runbook (deploy, roll back, rotate
the server key, reset the therapist password, read the logs).

### User Story 4 - Operated Safely (Priority: P2)

Logs contain no patient data, codes, passwords, or addresses; the host is patched; only HTTPS is
exposed; failed sign-ins and errors are visible to the operator; an uptime check alerts when the
front page is down.

### Edge Cases

- Two app instances must never write to the same SQLite file: the deployment runs exactly one
  instance and says so; scaling out would need a database server (a later feature).
- The clinic's YOLO-based Live Session needs a camera attached to the machine running it; on a
  cloud host it cannot use the therapist's camera. It stays a clinic-machine feature, or moves to
  the browser pose model (a later decision).
- Migrating an existing local record to the cloud: a documented one-time copy, with the local file
  kept as the backup.
- The provider's region determines where study data is stored; it must match the consent form.

## Requirements *(mandatory)*

- **FR-001**: The repository MUST contain everything needed to build and run Limber as one
  container: the patient service and the therapist app behind one reverse proxy that terminates
  HTTPS, serves the front page at `/`, and exposes the therapist app only under a path that the
  therapist sign-in protects.
- **FR-002**: Configuration MUST come from environment variables or mounted secrets (record path,
  server key, public address, therapist app address); no secret MAY be baked into the image or
  committed.
- **FR-003**: The deployment MUST refuse to start without a therapist password and a server key.
- **FR-004**: The record, the server key, and exports MUST live on a persistent volume; the image
  MUST be disposable.
- **FR-005**: A nightly encrypted backup with 14-day retention and a written, rehearsed restore
  procedure MUST exist.
- **FR-006**: Exactly one instance MUST run; the health check MUST verify that the record is
  readable and writable.
- **FR-007**: Application logs MUST NOT contain patient IDs with data, access codes, passwords,
  tokens, or visitor addresses.
- **FR-008**: The pose assets MUST be fetched and hash-checked at image build time, so patients'
  browsers load them from Limber only.
- **FR-009**: The runbook MUST cover deploy, roll back, key rotation, password reset, backup
  restore, and taking the service offline.
- **FR-010**: This feature MUST NOT be used with real clinic patients until the university's
  compliance review approves the provider, the agreement, and the procedures.

## Success Criteria

- **SC-001**: A patient on a phone completes sign-in and a camera session over the public address.
- **SC-002**: The therapist app cannot be reached without signing in (verified from outside).
- **SC-003**: A restore drill succeeds in under 30 minutes.
- **SC-004**: A redeploy loses no data.
- **SC-005**: An external scan shows only ports 80 (redirect) and 443 open.

## Decisions only the owner can make (max 3)

1. **[NEEDS CLARIFICATION: provider and who pays]** Options: (a) a small university-managed server
   (best fit for study data and later compliance; needs an IT contact); (b) a single small cloud
   virtual machine, roughly 10 to 25 US dollars a month, that you pay for; (c) a container platform
   with a persistent volume (simple deploys, similar cost). I cannot create any of these without
   your account and your go-ahead.
2. **[NEEDS CLARIFICATION: address]** A domain or subdomain is needed for a trusted certificate.
   Does the university provide one, or will you register one?
3. **[NEEDS CLARIFICATION: the clinic's camera features]** Should the therapist's Live Session and
   video analysis stay on the clinic machine (simplest), or must they also work from the cloud
   (needs a larger host, or moving them to the browser pose model)?

## Assumptions

- One installation, one therapist password, tens of patients, a handful at once.
- SQLite stays the record; a database server is out of scope.
- Depends on feature 007 complete (guided session, progress) and its therapist sign-in.
- Study participants only until compliance approval.
