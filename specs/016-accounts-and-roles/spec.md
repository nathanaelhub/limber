# Feature Specification: Accounts, Roles, Invitations, and Accessibility Preferences

**Feature Branch**: `016-accounts-and-roles`

**Created**: 2026-10-29

**Status**: Approved by the owner on 2026-10-30

**Input**: Owner: "with their requirements and ours, mostly have ours built out." The students' Limber
requirements 1–6 (see `specs/CROSSWALK-limber-requirements.md`): three roles, admin invitations, onboarding
from an invite link, username and password, therapists with their own caseloads, and a stored
accessibility preference. Our existing patient device codes stay.

## Constitution Check (Principle III, v1.2.0)

| Requirement | This feature |
|-------------|--------------|
| What crosses the network | Nothing new. Invite links are copied by the admin and handed over in person or by the clinic's own channel. |
| Pseudonymous IDs | Accounts store a display name chosen by the person and a username. Patient records stay keyed by pseudonymous ID; the display name is stored only in the account table, never in filenames, logs, or exports. |
| Deleting a patient | Removes the account, its sessions, invitations, and preferences with every other record. |

The display name is new identifying data. It is allowed because the user chose it, it is shown only to the
person and their own therapist, and no log line or export contains it. Tests use synthetic names only.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The Admin Invites Someone (Priority: P1)

An admin signs in, opens **People**, and sees everyone: display name, username, role, therapist (for a
patient), and status (invited, active, disabled). They choose **Invite**, pick a role, and for a patient
pick the therapist. Limber shows a single-use link valid for 7 days, with a copy button. The admin can
revoke an unused invite and disable an account.

**Acceptance Scenarios**:

1. **Given** an admin, **When** they invite a therapist, **Then** a link appears and the People list shows
   one "invited" row with the expiry date.
2. **Given** an invite older than 7 days, **When** it is opened, **Then** the page says it has expired and
   to ask for a new one; no account is created.
3. **Given** a revoked invite, **When** it is opened, **Then** the same expired message appears.
4. **Given** a therapist or patient, **When** they request the People page or its API, **Then** they get
   403.
5. **Given** the last active admin, **When** someone tries to disable them, **Then** it is refused.

### User Story 2 - Onboarding from the Link (Priority: P1)

The invited person opens the link and sees which role they were invited as. They enter a display name,
pick a username, set a password twice, and choose accessibility settings (larger text, higher contrast,
reduced motion), which preview live. They submit and are signed in.

**Acceptance Scenarios**:

1. **Given** a valid link, **When** the form is completed, **Then** an account with the invited role exists,
   the invite is used, and the person lands on their home page with their settings applied.
2. **Given** a used link, **When** it is opened again, **Then** it says the link was already used.
3. **Given** a taken username or a password under 12 characters, **Then** the form says so and keeps the
   other entries.
4. **Given** a patient invite, **Then** the new account is attached to the chosen therapist and that
   therapist sees the patient in their caseload.

### User Story 3 - Each Therapist Has Their Own Caseload (Priority: P1)

Today one password opens the whole record. After this feature each therapist signs in as themselves and
sees only their own patients; messages, logs, clips, and voice notes of another therapist's patient are
not reachable. An admin can move a patient to another therapist.

**Acceptance Scenarios**:

1. **Given** two therapists, **When** therapist A requests anything of therapist B's patient by ID,
   **Then** the answer is 404 (not 403, so existence is not revealed).
2. **Given** an admin reassigns a patient, **Then** the new therapist sees the full history and the old
   one sees nothing.
3. **Given** an upgrade from schema v13, **Then** the existing shared therapist login becomes the first
   therapist account and also an admin, every existing patient belongs to it, and the old password still
   works for it.

### User Story 4 - Accessibility Preferences Follow the Person (Priority: P2)

Anyone can change their settings under **My settings**. They apply on every page of both apps and on every
device the person signs in from.

**Acceptance Scenarios**:

1. **Given** larger text on, **Then** base text is at least 20px and nothing overflows at 320px width.
2. **Given** reduced motion on, **Then** no animation or auto-scrolling runs.
3. **Given** higher contrast on, **Then** all text meets WCAG AAA (7:1) contrast.

### Edge Cases

- A patient who keeps a device code and never makes a password: still works; the code sign-in is
  unchanged.
- Five wrong passwords in 15 minutes for one username, from any number of devices: further tries for that
  username wait, the wait doubling with each further failure (the limiter the access codes already use); the
  message does not say whether the username exists.
- An admin disables an account while it is signed in: its next request is signed out.
- An admin with no therapist role does not see clinical data, only People.

## Requirements *(mandatory)*

- **FR-001**: Roles are `admin`, `therapist`, `patient`. A person has one role, except that an admin may
  also be a therapist.
- **FR-002**: Passwords are stored only as a memory-hard hash (the scheme the therapist password already
  uses); 12 to 256 characters, the rule the therapist password already had.
- **FR-003**: An invite is a random token of at least 128 bits, stored only as a hash, single use, valid
  7 days, revocable.
- **FR-004**: Every therapist-side read and write checks that the patient belongs to the signed-in
  therapist, in the data layer, not only in the page.
- **FR-005**: Sign-in sessions are server-side and keep their existing limits: 8 hours for staff, the
  idle and absolute limits for a patient browser; disabling an account ends its sessions.
- **FR-006**: Staff preferences are stored on the account; a patient's are stored with the patient, so a
  patient who signs in with a code has them too. They are applied server-side on first render (no flash of
  the default style).
- **FR-007**: Schema v14 migrates v13 as in Story 3, scenario 3. An installation with no therapist
  password gets no account; its first admin is made with `portal accounts create-admin`.
- **FR-008**: The audit log records invite created, invite used, invite revoked, account disabled, patient
  reassigned, with the acting account and time; no display names in it.

## Key Entities

- **Account**: username, display name, role(s), password hash, status, preferences, created.
- **Invitation**: token hash, role, therapist (for a patient), created by, expires, used or revoked.
- **Caseload link**: patient ID → therapist account.

## Success Criteria

- **SC-001**: An admin can invite a therapist and that therapist is signed in within 2 minutes.
- **SC-002**: Tests prove a therapist cannot reach another therapist's patient through any existing route
  (one test per route family).
- **SC-003**: The existing 964 tests pass after the migration.

## Assumptions

- No email or SMS sending (see crosswalk).
- No password reset by email; an admin issues a fresh invite to reset.
- No single sign-on.
