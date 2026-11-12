# Tasks: A Hosted Demo on Vercel (feature 020)

Each slice is one issue, branch, and pull request, merged with the owner's go-ahead. Tests come first in every
slice. Local and self-hosted installs keep working after every slice (Story 3): the full suite passes with no
hosted settings at each merge.

## Slice 0: Spec and amendment

- [x] T001 Spec (`spec.md`), gate G1 spike and its results (PR #40)
- [x] T002 Constitution 1.5.0: the hosted-demo bullet in Principle III and the Canonical store exception
- [x] T003 This task list

## Slice A: The record on libSQL (Story 1, Story 3; FR-001 to FR-003b, FR-009)

- [x] T004 `libsql` in `requirements.txt` with a lower-bound pin; one connection function in `src/ptlog/` that
      returns `sqlite3` locally and a wrapped libSQL connection when `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`
      are set
- [x] T005 The wrapper's four rules, each with a test first (FR-002): rows by column name, `lastrowid` per
      statement, `IntegrityError`/`OperationalError` from libSQL's `ValueError`, commit before a script
- [x] T006 Store contract run: the store and portal tests run a second time through the wrapper against a libSQL
      local file in CI (no network); the 5 backup tests are skipped there with the reason stated
- [x] T007 Embedded replica on hosted installs (FR-003a): the copy under `/tmp`, a sync at the start of every
      request; test with two replicas of one local primary
- [x] T008 The simulated-data marker: `seed_demo.py` writes it; hosted settings without `LIMBER_DEMO=1` and the
      marker refuse to start, with a plain reason (FR-009, SC-005); `deploy preflight` reports the backend
- [-] T009 Dropped (FR-003b): with the embedded replica, Today's 253 reads are local and took the same 0.3 s as a
      13-statement page
- [x] T009a Writes take turns per instance (FR-003c); opening writes nothing and `last_seen_at` is refreshed at
      most once a minute (FR-003d)
- [x] T010 Live check, owner's machine only: the store against the Turso database, a write through one connection
      read through another (not in CI)

## Slice B: Files on Cloudflare R2 (Story 2; FR-004 to FR-006)

- [x] T011 `src/media/files.py`: put, get, delete, delete-everything-for-a-patient; the local folder by default,
      R2 when the `LIMBER_R2_*` settings are set; every write of an uploaded file goes through it (test: nothing
      else writes under the media folder)
- [x] T012 Signed links: upload and download links for one file, valid for minutes, issued only after the existing
      route checks; never logged or stored (FR-005); test that the bucket address never appears in a response body
- [x] T013 Clips and voice notes: parts stored through the interface, so consecutive parts may reach different
      instances (FR-006)
- [x] T014 Message attachments on hosted installs: the browser uploads each file straight to R2 with a signed
      link; Limber then checks size, type, and the media probe before attaching it; a file that fails is deleted
- [x] T015 Deleting a patient deletes their files in R2 (test against a fake bucket)
- [ ] T016 **Owner step**: add the bucket's CORS rule (uploads from the demo's address only); the exact rule is
      written in the slice's pull request

## Slice C: Shared settings (Story 1; FR-007, FR-008, FR-010 to FR-012)

- [x] T017 The sign-in limiter's counts kept in the record (test: five wrong passwords through two app instances
      lock the account)
- [x] T018 Server key from `PTASSIST_PORTAL_KEY` on hosted installs; refuse to start without it
- [x] T019 `/api/health` checks the record and the file store; 503 names which one is down
- [x] T020 `deploy demo-reset`: replace the hosted record and files with a fresh seed, print the new access codes
      once; refuse an unmarked record
- [x] T021 The hosted AI cap: 10 calls per account per day, set by `demo-reset`

## Slice D: The patient portal as Vercel Python functions (Story 1; FR-015)

- [x] T022 **Gate E (owner, Principle I)**: the portal imports the engine (`src.portal.live` → `src.live_session`
      → `analyze.py`), which loads Ultralytics and torch, and `src.ptlog.models` → `src.utils` loads OpenCV. Live
      sessions need only the engine's rep counting and angle maths. The owner chooses how the portal avoids
      the heavy imports: (a) load YOLO inside `analyze.py` only when a model is created (a two-line engine change),
      or (b) a torch-free copy of the counting rules outside the engine, kept identical by a test
- [x] T023 A hosted requirements file without torch, Ultralytics, OpenCV, or Streamlit; a test that importing the
      portal loads none of them
- [x] T024 Vercel entry point (ASGI) and `vercel.json`: the portal's pages, API, and static files; the Therapist
      door explains which clinic pages are online so far (Story 5, scenario 1)
- [x] T025 Deploy to `limber-demo` (Python, not the container preset); settings in Vercel: Turso, R2,
      `PTASSIST_PORTAL_KEY`, `LIMBER_DEMO=1`, the AI key
- [~] T026 (SC-001, SC-002 and the patient checks pass; photo upload waits for T016's CORS rule; SC-004 cold start not yet timed) Verify on the live site: 50 parallel signed-in requests (SC-001), a message written through one instance
      read through another (SC-002), first page from scaled to zero within 15 s (SC-004), and the patient dry run
      on a phone-sized browser
- [ ] T027 Remove the container-beta setup that 020 replaces (`Dockerfile.vercel`, the start-up seeding in demo
      mode on hosted installs), keeping the one-port mode for self-hosting

## Slice F: the patient live session on Vercel (before the clinic app)

The patient's camera session (`/ws/session`, `src/portal/live.py`) keeps its whole state in one instance's memory.
On Vercel a connection is cut at the function's time limit (300 s on Hobby), and `SessionStore` decides whether a
running session's owner is alive with `os.kill(pid, 0)` (`store.py`), which can mark a live session interrupted
when another instance opens the record.

- [ ] T031 Spike: does `/ws/session` upgrade on Vercel's Python runtime, when is it cut, and what does the browser
      see? Record the answers here
- [ ] T032 Session ownership by lease, not process id: the recorder writes an owner and `lease_until` into
      `source_extras` and renews it about every 30 s; recovery treats a session as alive while its lease runs
      (old rows: same host and a living process). No migration. Tests with two stores and fake clocks
- [ ] T033 A second device is refused across instances, using the lease in the record
- [ ] T034 The duration limit, chosen after T031: (A) reconnect in segments and resume the same session, or
      (B) stateless HTTP replay of the current set's frames
- [ ] T035 Deploy and run a camera session longer than the limit on the hosted demo

## Slice E onward: the therapist side (Story 5) and video (Story 6)

The therapist side on Vercel is the 019 clinic app, mounted at `/therapist`; each 019 slice deploys and is checked
on the hosted demo as it merges (`specs/019-clinic-app/tasks.md`).

- [ ] T028 019 slices 1 to 5 online (019 T011, T015, T018, T020, T023, T027)
- [ ] T029 **G5** = 019 **G2** (019 T030): browser pose against YOLO11 on the three Ultralytics clips
- [ ] T030 Hosted video analysis = 019 slice 6 (019 T028)

## Done when

- SC-001 to SC-005 pass, on the live site where they are about the live site.
- The patient dry run and, once 019 slices 1 to 5 are online, the therapist dry run pass on
  `limber-demo.vercel.app`.
- The full suite passes locally with no hosted settings.
