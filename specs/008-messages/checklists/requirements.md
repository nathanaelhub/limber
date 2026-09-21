# Specification Quality Checklist

**Created**: 2026-09-21
**Feature**: [spec.md](../spec.md)

- [x] Focused on user value; no framework or code detail
- [x] Requirements testable; success criteria measurable
- [x] Edge cases, dependencies, and assumptions identified
- [x] Constitution Principle III addressed (networked feature)
- [x] No [NEEDS CLARIFICATION] markers remain (owner accepted the recommended decisions on 2026-09-21)

## Implementation notes (2026-09-21)

- Suite green with no network, camera, or browser. A two-sided conversation was run in headless Chrome:
  the patient read the thread, sent a message, got the privacy warning for a phone number and sent
  anyway, and sent text containing markup; the therapist signed in through the front page, saw the
  unread count, opened the thread (marker for the warned message, markup shown literally), and replied;
  the patient saw the reply. No script dialog fired and no image element was created from the markup.
- Found and fixed during that run: hidden elements with a `display` style still showed (unread badge);
  the reply box kept its text after sending (now emptied by the send callback); Remove buttons were
  too narrow to read.
- US3 (context) shows the latest session and open flags; "start a message from a session" was not built.
- The command-line group and its test were written in the same step.
