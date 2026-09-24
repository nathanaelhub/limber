# Specification Quality Checklist

**Created**: 2026-09-24

- [x] Focused on user value; requirements testable; success criteria measurable
- [x] Edge cases, assumptions identified
- [x] Constitution Principle III check present (v1.2.0)
- [x] No [NEEDS CLARIFICATION] markers (decisions from the owner-approved plan of 2026-09-23)

## Implementation notes (2026-09-24)

- Suite green; media fixtures are generated at test time with PyAV (no binary committed).
- Phone-emulation run in Chrome: notice before the camera, preview, caption privacy warning then edit,
  upload in parts, the patient's list, the therapist (through the front-page door) playing the clip in
  the From the patient tab, Mark reviewed, the patient seeing "seen by your therapist", the queue
  listing "New uploads". No console errors.
- Not verified: a real phone camera (the run used a file), Safari playback of WebM, the Caddy body cap.
- Design notes: MOV and MP4 are one container family and are stored as .mp4; a file cut short but
  still readable is accepted as it is; encryption at rest is the host volume's, backups are encrypted.
- Test-first exception: the store methods were written with their tests.
