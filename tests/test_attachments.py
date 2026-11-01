"""Feature 017 US3 — photos and a PDF attached to messages: type sniffing, limits, metadata removed on the
host, files under the patient's media folder, and gone with the patient."""

import io
import os
import stat

import pytest
from PIL import ExifTags, Image, PngImagePlugin

from src.portal import attachments, messages, plans, uploads
from src.ptlog.models import PlanArchived
from src.ptlog.store import SessionStore

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def jpeg_with_gps(size=(40, 30)) -> bytes:
    img = Image.new("RGB", size, (200, 10, 10))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "SecretCam"
    exif[ExifTags.Base.Orientation] = 6                               # taken sideways
    exif[ExifTags.Base.GPSInfo] = {ExifTags.GPS.GPSLatitudeRef: "N", ExifTags.GPS.GPSLatitude: (36.0, 9.0, 0.0)}
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def png_with_text() -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_text("Location", "36.15N 86.78W")
    out = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(out, "PNG", pnginfo=info)
    return out.getvalue()


@pytest.fixture
def env(tmp_path, tmp_db, fake_clock):
    media_dir = tmp_path / "media"
    with SessionStore(tmp_db, clock=fake_clock).open() as s:
        s.add_patient("P-017")
        s.add_patient("P-018")
        s.conversation_set_enabled("P-017", True)
        yield s, media_dir


def send(env, files, text="see attached", sender="patient", **kw):
    store, media_dir = env
    return messages.send(store, "P-017", sender, text, files=files, media_dir=media_dir, **kw)


class TestSniffingAndLimits:
    def test_sniff(self):
        assert attachments.sniff(jpeg_with_gps()) == "image/jpeg"
        assert attachments.sniff(png_with_text()) == "image/png"
        assert attachments.sniff(PDF) == "application/pdf"
        assert attachments.sniff(b"\x00\x00\x00\x18ftypheic\x00\x00") == "image/heic"
        assert attachments.sniff(b"MZ\x90\x00") is None

    def test_content_must_match_its_stated_type(self):
        """Scenario 2."""
        with pytest.raises(attachments.AttachmentRejected, match="isn't the kind of file it says"):
            attachments.prepare([("image/jpeg", PDF)])
        with pytest.raises(attachments.AttachmentRejected, match="isn't the kind of file it says"):
            attachments.prepare([("application/pdf", b"<html>not a pdf</html>")])
        with pytest.raises(attachments.AttachmentRejected, match="photos .* or a PDF"):
            attachments.prepare([("application/x-msdownload", b"MZ")])

    def test_counts_and_sizes(self):
        photo = ("image/jpeg", jpeg_with_gps())
        assert len(attachments.prepare([photo] * 4)) == 4
        with pytest.raises(attachments.AttachmentRejected, match="up to 4"):
            attachments.prepare([photo] * 5)
        with pytest.raises(attachments.AttachmentRejected, match="one PDF on its own"):
            attachments.prepare([photo, ("application/pdf", PDF)])
        with pytest.raises(attachments.AttachmentRejected, match="15 MB"):
            attachments.prepare([("image/jpeg", b"\xff\xd8\xff" + b"0" * attachments.PHOTO_MAX)])
        with pytest.raises(attachments.AttachmentRejected, match="20 MB"):
            attachments.prepare([("application/pdf", b"%PDF-" + b"0" * attachments.PDF_MAX)])

    def test_a_damaged_photo_is_refused(self):
        with pytest.raises(attachments.AttachmentRejected, match="could not be opened"):
            attachments.prepare([("image/jpeg", b"\xff\xd8\xff\xe0garbage")])

    def test_heic_without_the_reader_is_refused_plainly(self, monkeypatch):
        monkeypatch.setattr(attachments, "_heic_reader", lambda: False)
        with pytest.raises(attachments.AttachmentRejected, match="HEIC"):
            attachments.prepare([("image/heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00")])


class TestMetadataIsRemoved:
    def test_gps_and_camera_tags_are_gone_and_orientation_is_kept(self):
        """Scenario 1."""
        (p,) = attachments.prepare([("image/jpeg", jpeg_with_gps())])
        stored = Image.open(io.BytesIO(p.data))
        assert dict(stored.getexif()) == {} and b"SecretCam" not in p.data
        assert (p.width, p.height) == (30, 40) and p.mime == "image/jpeg" and p.ext == "jpg"

    def test_png_text_chunks_are_gone(self):
        (p,) = attachments.prepare([("image/png", png_with_text())])
        assert b"Location" not in p.data and p.ext == "png" and Image.open(io.BytesIO(p.data)).mode == "RGBA"


class TestStoredWithMessages:
    def test_photos_are_stored_privately_with_the_message(self, env):
        store, media_dir = env
        m = send(env, [("image/jpeg", jpeg_with_gps()), ("image/png", png_with_text())])
        assert [a.kind for a in m.attachments] == ["photo", "photo"] and m.plan_id == store.plans("P-017")[0].id
        for a in m.attachments:
            path = attachments.path(media_dir, a)
            assert path.is_file() and path.parent.parent.name == "P-017" and path.name == f"{a.id}.{a.ext}"
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
            assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
        (stored,) = store.message_thread("P-017")
        assert [a.id for a in stored.attachments] == [a.id for a in m.attachments]

    def test_a_photo_alone_needs_no_text(self, env):
        m = send(env, [("image/jpeg", jpeg_with_gps())], text="")
        assert m.body == "" and len(m.attachments) == 1

    def test_a_refused_file_stores_nothing(self, env):
        store, media_dir = env
        with pytest.raises(attachments.AttachmentRejected):
            send(env, [("image/jpeg", jpeg_with_gps()), ("image/jpeg", PDF)])
        assert store.message_thread("P-017") == [] and not media_dir.exists()

    def test_the_therapist_can_attach_a_pdf(self, env):
        m = send(env, [("application/pdf", PDF)], text="Your home program", sender="therapist")
        assert m.attachments[0].kind == "document" and m.attachments[0].mime == "application/pdf"

    def test_only_the_owner_can_open_one(self, env):
        store, _ = env
        a = send(env, [("image/jpeg", jpeg_with_gps())]).attachments[0]
        assert attachments.get(store, "P-017", a.id).id == a.id
        assert attachments.get(store, "P-018", a.id) is None
        assert attachments.get(store, None, a.id) is not None               # the therapist
        assert attachments.get(store, "P-017", "not-a-uuid") is None
        store.restrict({"P-018"})
        assert attachments.get(store, None, a.id) is None                   # outside this therapist's caseload

    def test_a_removed_message_hides_its_attachments(self, env):
        store, _ = env
        m = send(env, [("image/jpeg", jpeg_with_gps())])
        store.message_remove(m.id)
        assert store.message_thread("P-017")[0].attachments == []
        assert attachments.get(store, "P-017", m.attachments[0].id) is None

    def test_deleting_one_leaves_a_marker_even_in_an_archived_plan(self, env):
        store, media_dir = env
        a = send(env, [("image/jpeg", jpeg_with_gps())]).attachments[0]
        plan = store.plans("P-017")[0]
        plans.complete(store, plan.id)
        plans.archive(store, plan.id)
        with pytest.raises(PlanArchived):
            send(env, [("image/jpeg", jpeg_with_gps())], plan_id=plan.id)
        assert attachments.delete(store, media_dir, "P-017", a.id, by="patient") is True
        assert not attachments.path(media_dir, a).exists()
        assert store.message_thread("P-017")[0].attachments[0].deleted_at is not None
        assert attachments.delete(store, media_dir, "P-017", a.id, by="patient") is False

    def test_files_go_with_the_patient(self, env):
        """Scenario 3."""
        store, media_dir = env
        a = send(env, [("application/pdf", PDF)]).attachments[0]
        path = attachments.path(media_dir, a)
        store.media_dir = media_dir
        store.delete_patient("P-017")
        assert not path.exists() and not (media_dir / "P-017").exists()

    def test_the_clip_reconciler_leaves_attachments_alone(self, env):
        store, media_dir = env
        a = send(env, [("image/jpeg", jpeg_with_gps())]).attachments[0]
        assert uploads.reconcile(store, media_dir)["files_without_row"] == 0
        assert attachments.path(media_dir, a).is_file()


def test_retention_deletes_a_year_after_archiving(env, fake_clock):
    store, media_dir = env
    a = send(env, [("image/jpeg", jpeg_with_gps())]).attachments[0]
    plan = store.plans("P-017")[0]
    assert attachments.run_retention(store, media_dir) == 0               # active: kept
    plans.complete(store, plan.id)
    plans.archive(store, plan.id)
    fake_clock.advance(364 * 86400)
    assert attachments.run_retention(store, media_dir) == 0
    fake_clock.advance(2 * 86400)
    assert attachments.run_retention(store, media_dir) == 1
    assert not attachments.path(media_dir, a).exists()
    assert store.attachment_get(a.id).deleted_by == "retention"
