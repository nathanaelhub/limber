# Implementation Plan: Messages (Therapist Inbox and Patient Conversation)

**Branch**: `008-messages` | **Date**: 2026-09-21 | **Spec**: [spec.md](spec.md)

## Summary

One conversation per patient, stored in the canonical record (schema v8). Rules live in a pure
module, `src/portal/messages.py`: sending with length and rate limits, the warn-and-allow privacy
check, per-side read marks, removal, the inbox, and unread counts. The therapist app gets an Inbox
page and a sidebar unread count; the roster and queue show unread messages; the patient portal gets
a Messages page and two API routes. Text is stored and shown as plain text only.

## Technical Context

Python 3.13; no new dependency. SQLite v8 (`conversations`, `messages`, `message_events`), forward-only.
Tests: pytest; Starlette `TestClient` for the patient routes; Streamlit `AppTest` for the Inbox; the
no-leak test extended to the message routes; a scripted two-sided conversation in Chrome.

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Engine | PASS | Not touched. |
| II. One record | PASS | `SessionStore` is the only writer of the three new tables. |
| III. Privacy (1.1.0) | PASS with the spec's stated risk | The spec carries the networked-feature check. Free text is new: messaging is off until the therapist turns it on per patient; a warning precedes sending text that looks identifying, the choice is recorded, and the therapist can remove a message. Message text is never written to logs or to the event history. |
| IV. Test-first | PASS | Test then code per task. |
| V. Simplicity | PASS | Polling, no push; no attachments; one shared inbox. |

## Structure

```text
src/ptlog/store.py          # schema v8 + conversation/message methods
src/ptlog/models.py         # Message, ConversationSummary, MessageError, NeedsConfirmation
src/portal/messages.py      # rules: check_text, send, thread, inbox, unread, remove, enable/disable
src/portal/viewmodels.py    # today_view gains messages {enabled, unread}; messages_view
src/ptlog/tracker.py        # roster unread count, queue kind "unread_messages"
interfaces/patient_portal.py, portal_static/messages.html, messages.js, nav link
interfaces/app.py           # Inbox page, sidebar count, Patients page toggle
interfaces/cli.py           # messages inbox|show|send|on|off
```
