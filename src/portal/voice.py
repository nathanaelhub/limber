"""A spoken note from the patient (feature 014).

The recording itself rides feature 011's pipeline, unchanged: chunked upload, isolated inspection,
private storage, retention, backups, and deletion with the patient. What this module adds is the one
thing that makes a voice note different from a clip — it arrives as a **message**, so the inbox, the
unread counts, and message removal all work without knowing anything about audio.

Whether a patient may send one is the conversation's rule, not a new one: messaging must be on, the
patient must not be discharged, and the hourly message limit applies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.ptlog.models import Media, PortalError
from src.ptlog.store import SessionStore

from . import messages, uploads

KIND = "voice"
NOTICE = ("Your voice note is stored on the Limber host and heard by your therapist. It is kept for 90 "
          "days after they listen to it (180 days if they do not), and you can delete it at any time. "
          "Please do not say your full name, address, or anything you would not want written down.")
SUGGESTED_SECONDS = 120          # what the page asks for; the service allows the 180 s of the media limits
OFF = "Messages are not turned on for you, so a voice note cannot be sent."


def may_send(store: SessionStore, patient_id: str) -> bool:
    return store.get_discharge(patient_id) is None and messages.is_enabled(store, patient_id)


def options(store: SessionStore, patient_id: str) -> dict:
    """What the page needs: whether it is offered at all, the notice, and the limits."""
    from src.media import probe
    limits = probe.LIMITS[KIND]
    return {"enabled": may_send(store, patient_id), "notice": NOTICE,
            "suggested_seconds": SUGGESTED_SECONDS,
            "max_seconds": int(limits["max_seconds"]), "max_bytes": int(limits["max_bytes"]),
            "count": len(uploads.list_media(store, patient_id, KIND))}


def check_may_send(store: SessionStore, patient_id: str) -> None:
    """Raise before a single byte is stored, so a refused note leaves nothing behind."""
    if store.get_discharge(patient_id) is not None:
        raise PortalError("Your programme has finished, so a voice note cannot be sent.")
    if not messages.is_enabled(store, patient_id):
        raise messages.MessagingOff(OFF)
    messages.check_rate(store, patient_id)


def finish(store: SessionStore, media_dir: Path, patient_id: str, upload_id: str,
           confirm: bool = False) -> Media:
    """Finish a voice upload and put it in the conversation as one message from the patient."""
    check_may_send(store, patient_id)
    media = uploads.finish(store, media_dir, patient_id, upload_id, confirm=confirm)
    if media.kind != KIND:
        return media                                  # a clip finished through the ordinary route
    message = store.message_add(patient_id, "patient", "", warned=False, media_id=media.id)
    store.message_event(patient_id, "sent", "patient", message.id)
    # Queue it to be written out, if this installation can do that at all. The note is playable either
    # way: the transcript is an aid, never a condition of the note arriving.
    from src.media import transcribe
    transcribe.queue_if_available(store, media.id)
    return store.media_get(media.id)


def playable(store: SessionStore, patient_id: str, media_id: str) -> Optional[Media]:
    """This patient's own voice note, if it is theirs and still there."""
    media = uploads.get_media(store, patient_id, media_id)
    if media is None or media.kind != KIND or media.deleted_at is not None:
        return None
    return media


def delete(store: SessionStore, media_dir: Path, patient_id: str, media_id: str, by: str) -> bool:
    """Delete a voice note: the file, its transcript, and the message it arrived as all go, leaving the
    marker in the conversation that something was removed."""
    media = uploads.get_media(store, patient_id, media_id)
    if media is None or media.kind != KIND or media.deleted_at is not None:
        return False
    message = store.message_for_media(media_id)
    removed = uploads.delete_media(store, media_dir, patient_id, media_id, by=by)
    if removed:
        store.transcription_drop(media_id)            # what was said must not outlive the recording
        if message is not None:
            store.message_remove(message.id)
    return removed
