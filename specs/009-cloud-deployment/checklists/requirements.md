# Specification Quality Checklist

**Created**: 2026-09-21
**Feature**: [spec.md](../spec.md)

- [x] Focused on user value; no framework or code detail
- [x] Requirements testable; success criteria measurable
- [x] Edge cases, dependencies, and assumptions identified
- [x] Constitution Principle III addressed (networked feature)
- [x] No [NEEDS CLARIFICATION] markers remain (owner accepted the recommended decisions on 2026-09-21)

## Implementation notes (2026-09-21)

- Verified by tests and by running them for real on the demo record: start-up checks, first-boot setup,
  encrypted backup, verification, restore to a second location, refusal of a wrong key, the read-write
  health check.
- Verified in Chrome: the therapist app under `/therapist` shows only the sign-in on a direct visit, and
  the front page's therapist door hands over to it.
- NOT verified: the container image (never built; Docker is not installed on the development machine),
  the Caddy configuration, automatic certificates, the proxy's log filtering, a phone over the public
  address (SC-001), an outside scan (SC-002, SC-005), a restore drill on a host (SC-003), a redeploy
  (SC-004). These need a host, which needs the owner's account and go-ahead.
- No cloud resource was created.
- Test-first exception: the start-up checks and their tests were written in the same step.
