# Specification Quality Checklist

**Created**: 2026-09-23
**Feature**: [spec.md](../spec.md)

- [x] Focused on user value; no framework detail
- [x] Requirements testable; success criteria measurable
- [x] Edge cases, dependencies, assumptions identified
- [x] Constitution Principle III check present (v1.2.0)
- [x] No [NEEDS CLARIFICATION] markers (decisions taken in the owner-approved plan of 2026-09-23)

## Implementation notes (2026-09-23)

- Suite green with no browser, camera, network, or model. Phone-emulation run in Chrome (iPhone 13
  profile): install hint with iOS steps, service worker registered, manifest served, online check-in
  stored, shell rendered offline with the banner, offline check-in queued and replayed exactly once on
  reconnect, Today's count updated, pain shown on progress, local storage empty after sign-out.
- Found in that run and fixed: the offline banner relied on the browser's online flag alone (now also
  shown when the request fails); link-style secondary buttons had no secondary style.
- Not verified: a real iPhone (standalone cookie jar, storage eviction) and Android install prompt.
- Test-first exceptions: the entries registry and the device sign-in change were written with their tests.
