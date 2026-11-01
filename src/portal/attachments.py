"""
Photos and documents attached to messages (feature 017). Pure rules over SessionStore and the disk.

Either side may attach up to 4 photos (JPEG, PNG, HEIC; 15 MB each) or one PDF (20 MB). The host checks
what a file is from its bytes, never from its name or stated type, and refuses a mismatch. Every photo is
decoded and written out again on the host, which drops location, camera, and any other metadata; HEIC
becomes JPEG so any browser can show it. Nothing goes to a third party.

Files live under the patient's pseudonymous media folder (the feature 011 layout), in an `attachments`
subfolder that the clip reconciler leaves alone, and go when the patient is deleted.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageOps

from src.ptlog.models import Attachment, Message, PortalError
from src.ptlog.store import SessionStore

PHOTO_MAX = 15 * 1024 * 1024
PDF_MAX = 20 * 1024 * 1024
MAX_PHOTOS = 4
RETENTION_AFTER_ARCHIVE_DAYS = 365
MAX_PIXELS = 50_000_000                       # a 15 MB file that decodes to more than this is refused
JPEG_QUALITY = 90
FOLDER = "attachments"
STATED = {"image/jpeg": "image/jpeg", "image/jpg": "image/jpeg", "image/png": "image/png",
          "image/heic": "image/heic", "image/heif": "image/heic", "application/pdf": "application/pdf"}
_HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis")


class AttachmentRejected(PortalError):
    pass


@dataclass
class Prepared:
    kind: str                                 # photo | document
    ext: str
    mime: str
    data: bytes
    width: int = 0
    height: int = 0


def sniff(data: bytes) -> Optional[str]:
    """What the bytes are, from their first few bytes."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "image/heic"
    return None


def _heic_reader() -> bool:
    """HEIC needs the optional pillow-heif plug-in. Without it, HEIC is refused with a plain message
    rather than stored unread, because an unread file cannot have its metadata removed."""
    try:
        import pillow_heif                     # noqa: F401  optional
    except ImportError:
        return False
    pillow_heif.register_heif_opener()
    return True


def _clean_photo(data: bytes, mime: str) -> Prepared:
    if mime == "image/heic" and not _heic_reader():
        raise AttachmentRejected("This Limber host can't read HEIC photos yet. On an iPhone, choose "
                                 "Settings › Camera › Formats › Most Compatible, or send a screenshot of the photo.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise AttachmentRejected("This photo is too large to show. Try a smaller one.")
            img.load()
            upright = ImageOps.exif_transpose(img)            # keep how it was taken, then drop the tags
    except AttachmentRejected:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, SyntaxError):
        raise AttachmentRejected("This photo could not be opened. It may be damaged.")
    keep_png = mime == "image/png"
    if keep_png:
        clean = upright.convert("RGBA" if "A" in upright.getbands() else "RGB")
    else:
        clean = upright.convert("RGB")
    clean.info = {}                                           # no EXIF, GPS, XMP, ICC, or text chunks
    out = io.BytesIO()
    if keep_png:
        clean.save(out, "PNG", optimize=True)
    else:
        clean.save(out, "JPEG", quality=JPEG_QUALITY)
    return Prepared(kind="photo", ext="png" if keep_png else "jpg", mime="image/png" if keep_png else "image/jpeg",
                    data=out.getvalue(), width=clean.width, height=clean.height)


def prepare(files: Sequence[Tuple[str, bytes]]) -> List[Prepared]:
    """Check and clean what is about to be sent: (stated type, bytes) pairs, in order."""
    if not files:
        return []
    stated = [STATED.get((t or "").split(";")[0].strip().lower()) for t, _ in files]
    if any(s is None for s in stated):
        raise AttachmentRejected("You can attach photos (JPEG, PNG, HEIC) or a PDF.")
    pdfs = sum(1 for s in stated if s == "application/pdf")
    if pdfs and len(files) > 1:
        raise AttachmentRejected("Attach one PDF on its own, or up to 4 photos.")
    if len(files) > MAX_PHOTOS:
        raise AttachmentRejected(f"You can attach up to {MAX_PHOTOS} photos to a message.")
    ready: List[Prepared] = []
    for (_, data), mime in zip(files, stated):
        limit = PDF_MAX if mime == "application/pdf" else PHOTO_MAX
        if len(data) > limit:
            raise AttachmentRejected(f"Each {'PDF' if mime == 'application/pdf' else 'photo'} can be up to "
                                     f"{limit // (1024 * 1024)} MB.")
        if not data or sniff(data) != mime:
            raise AttachmentRejected("This file isn't the kind of file it says it is, so it wasn't sent.")
        if mime == "application/pdf":
            ready.append(Prepared(kind="document", ext="pdf", mime=mime, data=data))
        else:
            ready.append(_clean_photo(data, mime))
    return ready


def path(media_dir: Path, a: Attachment) -> Path:
    return Path(media_dir) / a.patient_id / FOLDER / f"{a.id}.{a.ext}"


def attach(store: SessionStore, media_dir: Path, message: Message, ready: List[Prepared]) -> List[Attachment]:
    """Write the files, then their rows, and commit with the message. On failure nothing is left behind."""
    written: List[Path] = []
    try:
        rows = []
        for p in ready:
            a = Attachment(id=str(uuid.uuid4()), patient_id=message.patient_id, message_id=message.id,
                           plan_id=message.plan_id, kind=p.kind, ext=p.ext, mime=p.mime, bytes=len(p.data),
                           width=p.width, height=p.height, sha256=hashlib.sha256(p.data).hexdigest(), created_at="")
            target = path(media_dir, a)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(target.parent.parent, 0o700)
            os.chmod(target.parent, 0o700)
            target.write_bytes(p.data)
            os.chmod(target, 0o600)
            written.append(target)
            rows.append(store.attachment_add(a, commit=False))
        store.conn.commit()
        return rows
    except Exception:
        store.conn.rollback()
        for f in written:
            f.unlink(missing_ok=True)
        raise


def get(store: SessionStore, patient_id: Optional[str], attachment_id: str) -> Optional[Attachment]:
    """An attachment the viewer may open: the patient's own, or (patient_id None) any the store shows."""
    try:
        uuid.UUID(str(attachment_id))
    except ValueError:
        return None
    a = store.attachment_get(attachment_id)
    if a is None or (patient_id is not None and a.patient_id != patient_id):
        return None
    message = store.conn.execute("SELECT removed_at FROM messages WHERE id = ?", (a.message_id,)).fetchone()
    if message is None or message["removed_at"] is not None:
        return None
    return a


def delete(store: SessionStore, media_dir: Path, patient_id: Optional[str], attachment_id: str, by: str) -> bool:
    """Remove the file; the row stays as a marker. Allowed in an archived plan too."""
    a = get(store, patient_id, attachment_id)
    if a is None or a.deleted_at is not None:
        return False
    path(media_dir, a).unlink(missing_ok=True)
    store.attachment_mark_deleted(a.id, by)
    return True


def remove_all(media_dir: Path, patient_id: str) -> None:
    shutil.rmtree(Path(media_dir) / patient_id / FOLDER, ignore_errors=True)


def run_retention(store: SessionStore, media_dir: Path) -> int:
    """Delete files from plans archived more than a year ago (the constitution check's retention row);
    the rows stay as markers. Files in active and completed plans are kept."""
    from datetime import timedelta
    cutoff = (store.clock() - timedelta(days=RETENTION_AFTER_ARCHIVE_DAYS)).isoformat()
    rows = store.conn.execute(
        "SELECT a.id FROM attachments a JOIN plans_of_care p ON p.id = a.plan_id "
        "WHERE a.deleted_at IS NULL AND p.status = 'archived' AND p.archived_at < ?", (cutoff,)).fetchall()
    deleted = 0
    for r in rows:
        a = store.attachment_get(r["id"])
        if a is not None:
            path(media_dir, a).unlink(missing_ok=True)
            store.attachment_mark_deleted(a.id, "retention")
            deleted += 1
    return deleted
