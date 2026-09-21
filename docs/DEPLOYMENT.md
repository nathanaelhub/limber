# Limber: Hosting Runbook

For demo and consented study participants only. Do not host real clinic patients' data until the
university's compliance review has approved the provider, the agreement, and these procedures
(spec `specs/009-cloud-deployment/`, FR-010).

**Status of this runbook (2026-09-21)**: the Python parts (start-up checks, first-boot setup, encrypted
backup and restore, health check, the therapist app under `/therapist`) are tested. The container
image and the proxy configuration were written on a machine without Docker and **have not been built
or run yet**. Expect to fix small things on the first build, and rehearse a restore before relying on it.

## What runs

```text
internet ──443──> proxy (Caddy: HTTPS, certificates)
                     ├── /therapist*  ──> limber:8501   therapist app; shows only a sign-in until signed in
                     └── everything   ──> limber:8600   front page, patient view, session WebSocket
limber container ── /data volume: ptassist.db (the record), portal.key, exports/, backups/
```

One host, one `limber` container, one volume. **Never run two `limber` containers against one
volume**: the record is a single SQLite file with exactly one writer. The clinic's camera features
(Live Session with YOLO, video analysis) stay on the clinic machine; the hosted therapist app is for
review, tracker, inbox, and home access.

## What you need before starting

1. A host with Docker and Docker Compose: a university-managed server (preferred) or a small cloud
   machine (2 vCPU, 4 GB memory, 20 GB disk is enough; the image is large because of PyTorch).
2. A domain name pointing at the host, with ports 80 and 443 open and nothing else.
3. The repository on the host.

## Deploy

```bash
cd deploy
cp limber.env.example limber.env            # set LIMBER_DOMAIN and LIMBER_PUBLIC_ORIGIN (https)
mkdir -p secrets && chmod 700 secrets
printf '%s' 'a therapist password of 12 or more characters' > secrets/therapist_password
chmod 600 secrets/therapist_password
docker compose up -d --build
docker compose logs -f limber               # the start-up checks print ok / FAIL lines, then the service starts
```

The container refuses to start when there is no therapist password, no server key, the record is
not writable, the pose files are missing, or the public address is not https. The messages say what
to fix. After the first successful start, delete `secrets/therapist_password` from the host if you
prefer; the password is stored only as a salted hash in the record.

Then: open `https://<domain>/`, use the therapist door, add patients, issue access codes
(Patients page, "Home access").

## Bring an existing local record to the host (once)

Stop the local apps. Copy `data/ptassist.db` **and** `data/portal.key` (without the same key, every
access code stops working) into the volume before the first start:

```bash
docker compose run --rm --no-deps -v "$PWD/import:/import" limber sh -c 'cp /import/ptassist.db /import/portal.key /data/'
```

Keep the local files as your first backup.

## Backups (nightly, encrypted, 14 kept)

Host cron, as the user that runs Docker:

```cron
15 2 * * *  cd /path/to/repo/deploy && docker compose exec -T limber python interfaces/cli.py deploy backup --dest /data/backups --key-file /data/backup.key
```

- The backup is taken with SQLite's online backup while Limber keeps running, encrypted with an
  authenticated cipher, verified, and old files beyond fourteen are removed.
- **Copy `/data/backup.key` somewhere else once** (a password manager, a sealed envelope). A backup
  without its key is useless, and a key stored only beside the backups protects nothing.
- Copy `/data/backups/` off the host regularly (for example with the provider's snapshot or `rsync`).

## Restore (rehearse this before you need it)

```bash
docker compose stop limber
docker compose run --rm --no-deps limber python interfaces/cli.py deploy restore /data/backups/limber-YYYYMMDD-HHMMSS.db.enc --key-file /data/backup.key --force
docker compose start limber
```

A wrong key or a damaged file is refused before anything is changed. Target: a working copy from last
night's backup in under 30 minutes.

## Routine operations

| Task | How |
|------|-----|
| Update Limber | `git pull && docker compose up -d --build` (schema changes apply themselves on start) |
| Roll back | `git checkout <previous commit> && docker compose up -d --build`. Schema migrations are forward-only: restore last night's backup if the newer version had already changed the schema |
| Reset the therapist password | `docker compose exec limber python interfaces/cli.py portal admin set-password` (signs every therapist out) |
| Rotate the server key | Stop; delete `/data/portal.key`; start (a new key is created). **Every patient code stops working; issue new codes.** Do this if the volume may have been copied by someone else |
| See who has access | `docker compose exec limber python interfaces/cli.py portal code list` and `portal audit` |
| Take it offline | `docker compose stop proxy` (nothing is reachable; the record is untouched) |
| Health | `https://<domain>/api/health` returns `{"ok": true, "record": "ok", ...}`; 503 means the record cannot be written. Point an uptime monitor at it |

## What the logs contain

The patient service logs warnings and errors only, without request lines. The proxy's access log has
visitor addresses, request headers, and query strings removed, so access codes, passwords, single-use
passes, and addresses do not reach the logs. Message text is never logged. Check this on the first
run (`docker compose logs proxy | head`).

## Before real patients

University compliance approval of: the hosting provider and its health-data agreement; where the data
is stored (region); the consent text (it must say that body-point numbers and messages are stored with
the provider); who holds the therapist password and the backup key; breach and deletion procedures.
