"""Feature 011 T004 — chunked uploads, storage on disk with rows in the record, limits, retention."""

import hashlib
import os
import stat
from datetime import datetime, timedelta

import pytest

from src.media.probe import MediaRejected
from src.portal import uploads
from src.ptlog.models import PortalError
from src.ptlog.store import MIGRATIONS, SCHEMA_VERSION, SessionStore
from tests.fixtures import media as fx


@pytest.fixture
def env(tmp_path, tmp_db, fake_clock):
    media_dir = tmp_path / "media"
    store = SessionStore(tmp_db, clock=fake_clock).open()
    store.add_patient("P-017")
    store.add_patient("P-020")
    clip = fx.make_video(tmp_path / "src.mp4", seconds=2.0, audio=True)
    yield store, media_dir, clip
    store.close()


def send_whole(store, media_dir, patient, path, caption="", chunk=4096, confirm=False, kind="clip"):
    data = path.read_bytes()
    up = uploads.begin(store, media_dir, patient, kind, len(data), hashlib.sha256(data).hexdigest(), chunk_bytes=chunk)
    for n, start in enumerate(range(0, len(data), chunk)):
        uploads.put_part(store, media_dir, patient, up.id, n, data[start:start + chunk])
    return uploads.finish(store, media_dir, patient, up.id, caption=caption, confirm=confirm)


def test_schema_v10(env):
    store, _, _ = env
    tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert SCHEMA_VERSION >= 10 and {"media", "media_uploads"} <= tables and [v for v, _ in MIGRATIONS][-1] == SCHEMA_VERSION


def test_upload_lands_on_disk_with_a_row_and_private_permissions(env):
    store, media_dir, clip = env
    m = send_whole(store, media_dir, "P-017", clip, caption="Knee catching on the way down")
    assert m.kind == "clip" and m.codec == "h264" and m.ext == "mp4" and 1.5 <= m.duration <= 2.5 and m.width == 64
    path = uploads.media_path(media_dir, m)
    assert path.parent.name == "P-017" and path.name == f"{m.id}.mp4" and path.is_file()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert m.sha256 == hashlib.sha256(clip.read_bytes()).hexdigest() and m.caption == "Knee catching on the way down"
    assert not list((media_dir / ".incoming").glob("*")) if (media_dir / ".incoming").exists() else True
    assert store.conn.execute("SELECT COUNT(*) FROM media_uploads").fetchone()[0] == 0
    assert "src.mp4" not in str(store.conn.execute("SELECT * FROM media").fetchall())
    events = [(a.event, a.detail) for a in store.portal_audit_list("P-017")]
    assert events[0] == ("upload_stored", "clip") and "Knee" not in str(events)
    listed = uploads.list_media(store, "P-017")
    assert [x.id for x in listed] == [m.id] and uploads.list_media(store, "P-020") == []


def test_parts_can_arrive_out_of_order_and_be_resumed(env):
    store, media_dir, clip = env
    data = clip.read_bytes()
    up = uploads.begin(store, media_dir, "P-017", "clip", len(data), hashlib.sha256(data).hexdigest(), chunk_bytes=1024)
    parts = [data[i:i + 1024] for i in range(0, len(data), 1024)]
    assert len(parts) >= 4
    uploads.put_part(store, media_dir, "P-017", up.id, 2, parts[2])
    uploads.put_part(store, media_dir, "P-017", up.id, 0, parts[0])
    status = uploads.status(store, media_dir, "P-017", up.id)
    assert status.received == [0, 2] and status.total_parts == len(parts) and status.chunk_bytes == 1024
    with pytest.raises(PortalError):
        uploads.finish(store, media_dir, "P-017", up.id)                     # parts missing
    for n in range(len(parts)):
        if n not in (0, 2):
            uploads.put_part(store, media_dir, "P-017", up.id, n, parts[n])
    uploads.put_part(store, media_dir, "P-017", up.id, 1, parts[1])          # a duplicate part is harmless
    assert uploads.finish(store, media_dir, "P-017", up.id).sha256 == hashlib.sha256(data).hexdigest()


def test_wrong_hash_or_bad_file_is_refused_and_nothing_is_stored(env, tmp_path):
    store, media_dir, clip = env
    data = clip.read_bytes()
    up = uploads.begin(store, media_dir, "P-017", "clip", len(data), "0" * 64)
    uploads.put_part(store, media_dir, "P-017", up.id, 0, data)
    with pytest.raises(PortalError) as err:
        uploads.finish(store, media_dir, "P-017", up.id)
    assert "hash" in str(err.value).lower() or "changed" in str(err.value).lower()
    png = fx.make_png_named_mp4(tmp_path / "x.mp4")
    with pytest.raises(MediaRejected) as err:
        send_whole(store, media_dir, "P-017", png)
    assert err.value.reason == "not_media"
    assert uploads.list_media(store, "P-017") == [] and not (media_dir / "P-017").exists()
    assert store.portal_audit_list("P-017")[0].event == "upload_rejected"
    assert store.conn.execute("SELECT COUNT(*) FROM media_uploads").fetchone()[0] == 0


def test_limits(env):
    store, media_dir, clip = env
    data = clip.read_bytes(); digest = hashlib.sha256(data).hexdigest()
    with pytest.raises(PortalError):
        uploads.begin(store, media_dir, "P-017", "clip", 90 * 1024 * 1024, digest)            # declared size over the limit
    with pytest.raises(PortalError):
        uploads.begin(store, media_dir, "P-017", "clip", len(data), "not-a-hash")
    ups = [uploads.begin(store, media_dir, "P-017", "clip", len(data), digest) for _ in range(3)]
    with pytest.raises(PortalError) as err:
        uploads.begin(store, media_dir, "P-017", "clip", len(data), digest)                    # a fourth open upload
    assert "3" in str(err.value)
    for u in ups[1:]:
        uploads.abandon(store, media_dir, "P-017", u.id)
    up = ups[0]
    with pytest.raises(PortalError):
        uploads.put_part(store, media_dir, "P-017", up.id, 0, data + b"x" * 10)               # more bytes than declared
    with pytest.raises(PortalError):
        uploads.put_part(store, media_dir, "P-020", up.id, 0, data[:100])                      # not this patient's upload
    uploads.abandon(store, media_dir, "P-017", up.id)
    for _ in range(10):
        send_whole(store, media_dir, "P-017", clip)
    with pytest.raises(PortalError) as err:
        uploads.begin(store, media_dir, "P-017", "clip", len(data), digest)                    # eleventh clip today
    assert "10" in str(err.value)
    send_whole(store, media_dir, "P-020", clip)                                                # another patient is not affected


def test_expired_uploads_are_cleaned(env, fake_clock):
    store, media_dir, clip = env
    data = clip.read_bytes()
    up = uploads.begin(store, media_dir, "P-017", "clip", len(data), hashlib.sha256(data).hexdigest(), chunk_bytes=4096)
    uploads.put_part(store, media_dir, "P-017", up.id, 0, data[:4096])
    fake_clock.advance(3601)
    assert uploads.clean_expired(store, media_dir) == 1
    assert not (media_dir / ".incoming" / up.id).exists()
    with pytest.raises(PortalError):
        uploads.put_part(store, media_dir, "P-017", up.id, 1, data[4096:8192])


def test_patient_delete_leaves_a_marker_and_removes_the_file(env):
    store, media_dir, clip = env
    m = send_whole(store, media_dir, "P-017", clip)
    path = uploads.media_path(media_dir, m)
    assert uploads.delete_media(store, media_dir, "P-017", m.id, by="patient") is True
    assert not path.exists()
    (row,) = uploads.list_media(store, "P-017")
    assert row.deleted_at and row.deleted_by == "patient" and uploads.delete_media(store, media_dir, "P-017", m.id, by="patient") is False
    assert uploads.get_media(store, "P-020", m.id) is None                                    # not theirs
    assert store.portal_audit_list("P-017")[0].event == "media_deleted"


def test_review_and_retention(env, fake_clock):
    store, media_dir, clip = env
    reviewed = send_whole(store, media_dir, "P-017", clip)
    unreviewed = send_whole(store, media_dir, "P-017", clip)
    uploads.mark_reviewed(store, reviewed.id)
    assert uploads.get_media(store, "P-017", reviewed.id).reviewed_at is not None
    assert [x.id for x in uploads.unreviewed(store)["P-017"]] == [unreviewed.id]
    fake_clock.advance(91 * 86400)
    report = uploads.run_retention(store, media_dir)
    assert report == {"deleted": 1, "kept": 1}
    assert uploads.get_media(store, "P-017", reviewed.id).deleted_by == "retention"
    assert uploads.media_path(media_dir, unreviewed).exists()
    fake_clock.advance(90 * 86400)
    assert uploads.run_retention(store, media_dir) == {"deleted": 1, "kept": 0}


def test_reconcile_and_patient_cascade(env):
    store, media_dir, clip = env
    kept = send_whole(store, media_dir, "P-017", clip)
    lost = send_whole(store, media_dir, "P-017", clip)
    uploads.media_path(media_dir, lost).unlink()                                               # a file went missing
    stray = media_dir / "P-017" / "00000000-0000-4000-8000-000000000000.mp4"
    stray.write_bytes(b"orphan")                                                               # a file without a row
    report = uploads.reconcile(store, media_dir)
    assert report == {"rows_without_file": 1, "files_without_row": 1}
    assert uploads.get_media(store, "P-017", lost.id).deleted_by == "missing" and not stray.exists()
    assert uploads.media_path(media_dir, kept).exists()
    store.delete_patient("P-017")
    assert not (media_dir / "P-017").exists()
    assert store.conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0


def test_caption_privacy_check(env):
    store, media_dir, clip = env
    from src.portal.messages import NeedsConfirmation
    with pytest.raises(NeedsConfirmation):
        send_whole(store, media_dir, "P-017", clip, caption="Filmed by Jane Smith")
    assert uploads.list_media(store, "P-017") == []
    m = send_whole(store, media_dir, "P-017", clip, caption="Filmed by Jane Smith", confirm=True)
    assert m.warned is True
    with pytest.raises(PortalError):
        send_whole(store, media_dir, "P-017", clip, caption="x" * 201)
