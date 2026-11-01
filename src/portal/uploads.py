"""
Uploads from the patient's phone (feature 011): a chunked, resumable transfer into a per-upload
folder, then assembly, hash check, isolated inspection, and a move into `data/media/<patient>/`.
Limits per patient, expiry of unfinished uploads, patient and therapist deletion (a marker stays),
retention, and reconciliation of rows against files. Pure rules over SessionStore and the disk.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.media import probe
from src.portal import messages
from src.ptlog.models import Media, PortalError
from src.ptlog.store import SessionStore

CHUNK_BYTES = 4 * 1024 * 1024
OPEN_PER_PATIENT = 3
PER_DAY = {"clip": (10, 250 * 1024 * 1024), "voice": (30, 60 * 1024 * 1024)}
UPLOAD_LIFETIME = timedelta(hours=1)
CAPTION_MAX = 200
NOTICE = ("Your clip is stored on the Limber host and seen by your therapist. It is kept for 90 days after they "
          "review it (180 days at most) and you can delete it at any time. Do not include other people, and do not say "
          "your name in the video.")
RETENTION_REVIEWED = timedelta(days=90)
RETENTION_UNREVIEWED = timedelta(days=180)
_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class UploadStatus:
    id: str
    kind: str
    total_bytes: int
    chunk_bytes: int
    total_parts: int
    received: List[int]


def _incoming(media_dir: Path, upload_id: str) -> Path:
    return Path(media_dir) / ".incoming" / upload_id


def media_path(media_dir: Path, media: Media) -> Path:
    return Path(media_dir) / media.patient_id / f"{media.id}.{media.ext}"


def _own_upload(store: SessionStore, patient_id: str, upload_id: str) -> dict:
    if not _ID.match(upload_id or ""):
        raise PortalError("Unknown upload.")
    up = store.upload_get(upload_id)
    if up is None or up["patient_id"] != patient_id:
        raise PortalError("Unknown upload.")
    if store.clock().isoformat() >= up["expires_at"]:
        raise PortalError("This upload timed out. Please start again.")
    return up


MIN_CHUNK, MAX_CHUNK = 1024, CHUNK_BYTES


def begin(store: SessionStore, media_dir: Path, patient_id: str, kind: str, total_bytes, sha256: str,
          chunk_bytes: int = CHUNK_BYTES):
    """Open an upload. Refuses over-limit declarations before a byte is sent."""
    store.require_writable_plan(patient_id)           # an archived plan takes no new uploads (feature 017)
    if not isinstance(chunk_bytes, int) or isinstance(chunk_bytes, bool) or not MIN_CHUNK <= chunk_bytes <= MAX_CHUNK:
        raise PortalError("The part size is out of range.")
    if kind not in PER_DAY:
        raise PortalError("Unknown upload kind.")
    if not isinstance(total_bytes, int) or isinstance(total_bytes, bool) or total_bytes <= 0:
        raise PortalError("The upload size must be a positive number of bytes.")
    if total_bytes > probe.LIMITS[kind]["max_bytes"]:
        raise PortalError(probe.REASONS["too_large"])
    if not isinstance(sha256, str) or not _HEX64.match(sha256.lower()):
        raise PortalError("The upload needs the file's SHA-256.")
    store._require_patient(patient_id)
    if store.get_discharge(patient_id) is not None:
        raise PortalError("Uploads are closed for a discharged patient.")
    if len(store.uploads_open(patient_id)) >= OPEN_PER_PATIENT:
        raise PortalError(f"You have {OPEN_PER_PATIENT} uploads in progress. Finish or cancel one first.")
    count_limit, bytes_limit = PER_DAY[kind]
    count, size = store.media_count_since(patient_id, kind, store.clock() - timedelta(hours=24))
    if count >= count_limit or size + total_bytes > bytes_limit:
        raise PortalError(f"You can send up to {count_limit} clips a day. Please try again tomorrow.")
    upload_id = str(uuid.uuid4())
    store.upload_add(upload_id, patient_id, kind, total_bytes, chunk_bytes, sha256.lower(), store.clock() + UPLOAD_LIFETIME)
    folder = _incoming(media_dir, upload_id)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    store.portal_audit_add("upload_started", patient_id, None, kind)
    return status(store, media_dir, patient_id, upload_id)


def status(store: SessionStore, media_dir: Path, patient_id: str, upload_id: str) -> UploadStatus:
    up = _own_upload(store, patient_id, upload_id)
    folder = _incoming(media_dir, upload_id)
    received = sorted(int(p.name[5:]) for p in folder.glob("part-*")) if folder.exists() else []
    total_parts = -(-up["total_bytes"] // up["chunk_bytes"])
    return UploadStatus(upload_id, up["kind"], up["total_bytes"], up["chunk_bytes"], total_parts, received)


def put_part(store: SessionStore, media_dir: Path, patient_id: str, upload_id: str, index: int, data: bytes) -> UploadStatus:
    up = _own_upload(store, patient_id, upload_id)
    total_parts = -(-up["total_bytes"] // up["chunk_bytes"])
    if not isinstance(index, int) or not 0 <= index < total_parts:
        raise PortalError("Unknown part.")
    expected = up["chunk_bytes"] if index < total_parts - 1 else up["total_bytes"] - up["chunk_bytes"] * (total_parts - 1)
    if len(data) != expected:
        raise PortalError("This part does not have the expected size.")
    folder = _incoming(media_dir, upload_id)
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / f"part-{index}"
    tmp = folder / f"part-{index}.tmp"
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    tmp.replace(part)
    return status(store, media_dir, patient_id, upload_id)


def abandon(store: SessionStore, media_dir: Path, patient_id: str, upload_id: str) -> None:
    _own_upload(store, patient_id, upload_id)
    shutil.rmtree(_incoming(media_dir, upload_id), ignore_errors=True)
    store.upload_delete(upload_id)


def finish(store: SessionStore, media_dir: Path, patient_id: str, upload_id: str, caption: str = "",
           confirm: bool = False, message_id: Optional[int] = None) -> Media:
    """Assemble the parts, check the hash, inspect the file in isolation, and store it. On refusal the
    parts and the upload row are removed and nothing is kept."""
    up = _own_upload(store, patient_id, upload_id)
    st = status(store, media_dir, patient_id, upload_id)
    if st.received != list(range(st.total_parts)):
        missing = sorted(set(range(st.total_parts)) - set(st.received))
        raise PortalError(f"The upload is missing part(s) {missing[:5]}.")
    caption = (caption or "").strip()
    if len(caption) > CAPTION_MAX:
        raise PortalError(f"A caption can be up to {CAPTION_MAX} characters.")
    reasons = messages.check_text(caption) if caption else []
    if reasons and not confirm:
        raise messages.NeedsConfirmation(reasons)
    folder = _incoming(media_dir, upload_id)
    assembled = folder / "assembled"
    digest = hashlib.sha256()
    with assembled.open("wb") as out:
        for n in range(st.total_parts):
            chunk = (folder / f"part-{n}").read_bytes()
            digest.update(chunk)
            out.write(chunk)
    try:
        if digest.hexdigest() != up["sha256"] or assembled.stat().st_size != up["total_bytes"]:
            raise PortalError("The file changed during upload (hash mismatch). Please send it again.")
        try:
            info = probe.run_isolated(assembled, kind=up["kind"])
        except probe.MediaRejected as rejected:
            store.portal_audit_add("upload_rejected", patient_id, None, rejected.reason)
            raise
        media_id = str(uuid.uuid4())
        media = Media(id=media_id, patient_id=patient_id, kind=up["kind"], ext=info.ext, container=info.container,
                      codec=info.codec, bytes=info.bytes, duration=info.duration, width=info.width, height=info.height,
                      sha256=up["sha256"], caption=caption, warned=bool(reasons), message_id=message_id)
        target = media_path(media_dir, media)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(target.parent, 0o700)
        os.chmod(assembled, 0o600)
        assembled.replace(target)
        stored = store.media_add(media)
        store.portal_audit_add("upload_stored", patient_id, None, up["kind"])
        return stored
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        store.upload_delete(upload_id)


def clean_expired(store: SessionStore, media_dir: Path) -> int:
    now = store.clock().isoformat()
    removed = 0
    for up in store.uploads_open():
        if now >= up["expires_at"]:
            shutil.rmtree(_incoming(media_dir, up["id"]), ignore_errors=True)
            store.upload_delete(up["id"])
            removed += 1
    return removed


def list_media(store: SessionStore, patient_id: str, kind: Optional[str] = "clip") -> List[Media]:
    return store.media_list(patient_id, kind)


def get_media(store: SessionStore, patient_id: str, media_id: str) -> Optional[Media]:
    """The patient's own media only; anyone else's id is simply not found."""
    if not _ID.match(media_id or ""):
        return None
    m = store.media_get(media_id)
    return m if m is not None and m.patient_id == patient_id else None


def _remove_file(media_dir: Path, media: Media) -> None:
    try:
        media_path(media_dir, media).unlink()
    except FileNotFoundError:
        pass


def delete_media(store: SessionStore, media_dir: Path, patient_id: Optional[str], media_id: str, by: str) -> bool:
    """Remove the file; the row stays as a marker. `patient_id` None means the therapist acts."""
    m = store.media_get(media_id) if _ID.match(media_id or "") else None
    if m is None or m.deleted_at is not None or (patient_id is not None and m.patient_id != patient_id):
        return False
    _remove_file(media_dir, m)
    store.media_update(media_id, deleted_at=store.clock().isoformat(), deleted_by=by)
    store.portal_audit_add("media_deleted", m.patient_id, None, by)
    return True


def mark_reviewed(store: SessionStore, media_id: str) -> bool:
    m = store.media_get(media_id)
    if m is None or m.reviewed_at is not None:
        return False
    store.media_update(media_id, reviewed_at=store.clock().isoformat())
    store.portal_audit_add("media_reviewed", m.patient_id, None, m.kind)
    return True


def unreviewed(store: SessionStore) -> Dict[str, List[Media]]:
    result: Dict[str, List[Media]] = {}
    for m in store.media_list(kind="clip", live_only=True):
        if m.reviewed_at is None:
            result.setdefault(m.patient_id, []).append(m)
    return result


def run_retention(store: SessionStore, media_dir: Path) -> Dict[str, int]:
    """Delete files kept longer than the retention period; rows stay as markers."""
    now = store.clock()
    deleted = kept = 0
    for m in store.media_list(live_only=True):
        anchor = datetime.fromisoformat(m.reviewed_at) if m.reviewed_at else datetime.fromisoformat(m.created_at)
        limit = RETENTION_REVIEWED if m.reviewed_at else RETENTION_UNREVIEWED
        if now - anchor > limit:
            _remove_file(media_dir, m)
            store.media_update(m.id, deleted_at=now.isoformat(), deleted_by="retention")
            deleted += 1
        else:
            kept += 1
    return {"deleted": deleted, "kept": kept}


def reconcile(store: SessionStore, media_dir: Path) -> Dict[str, int]:
    """Rows without a file are marked missing; files without a row are removed."""
    media_dir = Path(media_dir)
    known = {}
    rows_without_file = 0
    for m in store.media_list(live_only=True):
        p = media_path(media_dir, m)
        known[p] = m
        if not p.exists():
            store.media_update(m.id, deleted_at=store.clock().isoformat(), deleted_by="missing")
            rows_without_file += 1
    files_without_row = 0
    if media_dir.exists():
        for patient_dir in media_dir.iterdir():
            if patient_dir.name.startswith(".") or not patient_dir.is_dir():
                continue
            for f in patient_dir.iterdir():
                if f.is_file() and f not in known:
                    f.unlink()
                    files_without_row += 1
    return {"rows_without_file": rows_without_file, "files_without_row": files_without_row}
