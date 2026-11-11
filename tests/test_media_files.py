"""Feature 020 slice B: one storage interface for uploaded files (FR-004, FR-005). The local folder by default;
the hosted demo's Cloudflare R2 bucket when the LIMBER_R2_* settings are set. R2 is exercised here with an
in-memory fake of the five S3 calls Limber uses; the real bucket is checked live on the owner's machine."""

from urllib.parse import parse_qs, urlparse

import pytest

from src.media import files


class FakeS3:
    """put_object, get_object, delete_objects, list_objects_v2, generate_presigned_url: nothing else is used."""

    def __init__(self):
        self.objects = {}
        self.signed = []

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.read()

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise files.NotFound(Key)

        class B:
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data
        return {"Body": B(self.objects[(Bucket, Key)])}

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.objects.pop((Bucket, o["Key"]), None)

    def list_objects_v2(self, Bucket, Prefix, **kw):
        keys = sorted(k for b, k in self.objects if b == Bucket and k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.signed.append((op, Params, ExpiresIn))
        q = "&".join(f"{k}={v}" for k, v in Params.items() if k not in ("Bucket", "Key"))
        return f"https://acct.r2.cloudflarestorage.com/{Params['Bucket']}/{Params['Key']}?X-Amz-Expires={ExpiresIn}&{q}"


@pytest.fixture(params=["local", "r2"])
def store_files(request, tmp_path):
    if request.param == "local":
        return files.LocalFiles(tmp_path / "media")
    return files.R2Files(FakeS3(), bucket="limber", prefix="media/", endpoint="https://acct.r2.cloudflarestorage.com")


def test_put_get_exists_delete(store_files):
    store_files.put_bytes("P-017/a.mp4", b"clip")
    assert store_files.exists("P-017/a.mp4") and store_files.get_bytes("P-017/a.mp4") == b"clip"
    store_files.delete("P-017/a.mp4")
    assert not store_files.exists("P-017/a.mp4")
    store_files.delete("P-017/a.mp4")                                 # deleting twice is fine


def test_list_and_delete_a_prefix(store_files):
    for name in ("P-017/a.mp4", "P-017/attachments/b.jpg", "P-018/c.mp4"):
        store_files.put_bytes(name, b"x")
    assert store_files.list("P-017/") == ["P-017/a.mp4", "P-017/attachments/b.jpg"]
    store_files.delete_prefix("P-017/")
    assert store_files.list("P-017/") == [] and store_files.exists("P-018/c.mp4")


def test_a_local_copy_for_tools_that_need_a_path(store_files, tmp_path):
    store_files.put_bytes("P-017/a.mp4", b"clip")
    with store_files.local_path("P-017/a.mp4") as p:
        assert p.read_bytes() == b"clip"
        held = p
    if store_files.remote:
        assert not held.exists()                                     # the temporary copy is removed afterwards


def test_put_file_moves_an_assembled_upload(store_files, tmp_path):
    src = tmp_path / "assembled"
    src.write_bytes(b"whole file")
    store_files.put_file("P-017/a.mp4", src)
    assert store_files.get_bytes("P-017/a.mp4") == b"whole file" and not src.exists()


def test_paths_cannot_escape_the_store(store_files):
    for bad in ("../x", "/etc/passwd", "P-017/../../x", ""):
        with pytest.raises(ValueError):
            store_files.put_bytes(bad, b"x")


def test_local_response_serves_the_file_with_its_headers(tmp_path):
    lf = files.LocalFiles(tmp_path / "media")
    lf.put_bytes("P-017/a.jpg", b"img")
    r = lf.response("P-017/a.jpg", "image/jpeg", "photo.jpg", {"X-Content-Type-Options": "nosniff"})
    assert r.status_code == 200 and r.media_type == "image/jpeg"
    assert r.headers["Cache-Control"] == "private, no-store" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert lf.response("P-017/missing.jpg", "image/jpeg", "x.jpg") is None


def test_r2_response_is_a_short_signed_redirect_that_keeps_the_headers():
    fake = FakeS3()
    r2 = files.R2Files(fake, bucket="limber", prefix="media/", endpoint="https://acct.r2.cloudflarestorage.com")
    r2.put_bytes("P-017/a.jpg", b"img")
    r = r2.response("P-017/a.jpg", "image/jpeg", "photo.jpg")
    assert r.status_code == 302 and r.headers["Cache-Control"] == "private, no-store"
    url = urlparse(r.headers["location"])
    assert url.netloc == "acct.r2.cloudflarestorage.com" and url.path == "/limber/media/P-017/a.jpg"
    op, params, seconds = fake.signed[-1]
    assert op == "get_object" and seconds <= files.SIGNED_SECONDS <= 600
    assert params["ResponseContentType"] == "image/jpeg" and params["ResponseCacheControl"] == "private, no-store"
    assert params["ResponseContentDisposition"] == 'inline; filename="photo.jpg"'
    assert r2.response("P-017/missing.jpg", "image/jpeg", "x.jpg") is None


def test_r2_upload_link_is_for_one_file_and_one_type():
    fake = FakeS3()
    r2 = files.R2Files(fake, bucket="limber", prefix="media/", endpoint="https://acct.r2.cloudflarestorage.com")
    url = r2.signed_put("P-017/attachments/x.jpg", "image/jpeg")
    op, params, seconds = fake.signed[-1]
    assert op == "put_object" and params["Key"] == "media/P-017/attachments/x.jpg"
    assert params["ContentType"] == "image/jpeg" and seconds <= files.SIGNED_SECONDS
    assert "X-Amz-Expires" in parse_qs(urlparse(url).query)


def test_the_local_store_has_no_upload_links(tmp_path):
    with pytest.raises(NotImplementedError):
        files.LocalFiles(tmp_path).signed_put("P-017/x.jpg", "image/jpeg")


def test_choice_follows_the_settings(tmp_path, monkeypatch):
    for k in ("LIMBER_R2_ACCOUNT_ID", "LIMBER_R2_BUCKET", "LIMBER_R2_ACCESS_KEY_ID", "LIMBER_R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert isinstance(files.at(tmp_path / "media"), files.LocalFiles) and files.r2_origin() is None
    monkeypatch.setenv("LIMBER_R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("LIMBER_R2_BUCKET", "limber")
    monkeypatch.setenv("LIMBER_R2_ACCESS_KEY_ID", "id")
    monkeypatch.setenv("LIMBER_R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setattr(files, "_s3_client", lambda account, key_id, secret: FakeS3())
    chosen = files.at(tmp_path / "media")
    assert isinstance(chosen, files.R2Files) and files.r2_origin() == "https://acct.r2.cloudflarestorage.com"


# ---- the patient portal on R2 (FR-005) -------------------------------------------------------------------------

@pytest.fixture
def r2_portal(tmp_db, monkeypatch):
    from starlette.testclient import TestClient
    from interfaces.patient_portal import create_app
    from src.portal import access
    from src.ptlog.store import SessionStore
    from tests.test_attachments import jpeg_with_gps
    fake = FakeS3()
    for k, v in (("LIMBER_R2_ACCOUNT_ID", "acct"), ("LIMBER_R2_BUCKET", "limber"),
                 ("LIMBER_R2_ACCESS_KEY_ID", "id"), ("LIMBER_R2_SECRET_ACCESS_KEY", "secret")):
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(files, "_s3_client", lambda *a: fake)
    monkeypatch.setattr(files, "_cached", {})
    key, origin = b"k" * 32, "http://testserver"
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
        s.conversation_set_enabled("P-017", True)
        plan = s.plans("P-017")[0]
        code = access.issue_code(s, key, "P-017")[0]
    with TestClient(create_app(db_path=tmp_db, key=key, allowed_origins=[origin]), base_url=origin,
                    follow_redirects=False) as c:
        assert c.post("/api/login", json={"code": code}, headers={"Origin": origin}).status_code == 200
        yield c, fake, plan, jpeg_with_gps, tmp_db


def test_the_policy_allows_the_bucket_only_when_r2_is_used(r2_portal, tmp_db, monkeypatch):
    c, *_ = r2_portal
    csp = c.get("/").headers["content-security-policy"]
    for directive in ("img-src", "media-src", "connect-src"):
        part = [d for d in csp.split(";") if d.strip().startswith(directive)][0]
        assert "https://acct.r2.cloudflarestorage.com" in part, directive
    monkeypatch.delenv("LIMBER_R2_ACCOUNT_ID")
    from starlette.testclient import TestClient
    from interfaces.patient_portal import create_app
    local = TestClient(create_app(db_path=tmp_db, key=b"k" * 32, allowed_origins=["http://testserver"]))
    assert "r2.cloudflarestorage.com" not in local.get("/").headers["content-security-policy"]


def test_a_photo_goes_to_the_bucket_and_opens_by_signed_link(r2_portal):
    c, fake, plan, jpeg, _ = r2_portal
    r = c.post(f"/api/plans/{plan.id}/messages", headers={"Origin": "http://testserver"}, data={"text": "swelling"},
               files=[("files", ("knee.jpg", jpeg(), "image/jpeg"))])
    assert r.status_code == 201, r.text
    a = r.json()["attachments"][0]
    assert ("limber", f"media/P-017/attachments/{a['id']}.jpg") in fake.objects
    got = c.get(f"/api/attachments/{a['id']}")
    assert got.status_code == 302 and got.headers["location"].startswith("https://acct.r2.cloudflarestorage.com/limber/")
    assert "no-store" in got.headers["cache-control"]
    assert c.delete(f"/api/attachments/{a['id']}", headers={"Origin": "http://testserver"}).status_code == 200
    assert ("limber", f"media/P-017/attachments/{a['id']}.jpg") not in fake.objects


def test_deleting_a_patient_empties_their_folder_in_the_bucket(r2_portal):
    c, fake, plan, jpeg, db = r2_portal
    c.post(f"/api/plans/{plan.id}/messages", headers={"Origin": "http://testserver"}, data={"text": "x"},
           files=[("files", ("k.jpg", jpeg(), "image/jpeg"))])
    assert any(k.startswith("media/P-017/") for _, k in fake.objects)
    from src.ptlog.store import SessionStore
    with SessionStore(db).open() as s:
        s.delete_patient("P-017")
    assert not any(k.startswith("media/P-017/") for _, k in fake.objects)


# ---- message attachments straight to R2 (FR-006): past Vercel's 4.5 MB request limit ---------------------------

def _links(c, files_declared):
    return c.post("/api/attachments/upload-links", headers={"Origin": "http://testserver"}, json={"files": files_declared})


def _upload(fake, link, data):
    """What the browser does with a signed link: PUT the bytes straight to the bucket."""
    key = urlparse(link["url"]).path.split("/limber/", 1)[1]
    fake.objects[("limber", key)] = data


def test_local_installs_keep_the_single_upload(tmp_db):
    from starlette.testclient import TestClient
    from interfaces.patient_portal import create_app
    from src.portal import access
    from src.ptlog.store import SessionStore
    with SessionStore(tmp_db).open() as s:
        s.add_patient("P-017")
        code = access.issue_code(s, b"k" * 32, "P-017")[0]
    c = TestClient(create_app(db_path=tmp_db, key=b"k" * 32, allowed_origins=["http://testserver"]), base_url="http://testserver")
    c.post("/api/login", json={"code": code}, headers={"Origin": "http://testserver"})
    assert _links(c, [{"type": "image/jpeg", "size": 1000}]).status_code == 501


def test_photos_upload_straight_to_the_bucket_then_are_checked_and_cleaned(r2_portal):
    c, fake, plan, jpeg, _ = r2_portal
    photo = jpeg()
    r = _links(c, [{"type": "image/jpeg", "size": len(photo)}, {"type": "image/jpeg", "size": len(photo)}])
    assert r.status_code == 200, r.text
    links = r.json()["uploads"]
    assert len(links) == 2 and all(link["key"].startswith(".incoming/attachments/P-017/") for link in links)
    for link in links:
        _upload(fake, link, photo)
    sent = c.post(f"/api/plans/{plan.id}/messages", headers={"Origin": "http://testserver"},
                  json={"text": "swelling", "uploaded": [link["key"] for link in links]})
    assert sent.status_code == 201, sent.text
    attached = sent.json()["attachments"]
    assert [a["kind"] for a in attached] == ["photo", "photo"] and (attached[0]["width"], attached[0]["height"]) == (30, 40)
    stored = fake.objects[("limber", f"media/P-017/attachments/{attached[0]['id']}.jpg")]
    from PIL import Image
    import io
    assert dict(Image.open(io.BytesIO(stored)).getexif()) == {}                     # location data stripped, as before
    assert not [k for _, k in fake.objects if k.startswith("media/.incoming/")]      # the raw uploads are gone


def test_upload_links_refuse_what_a_message_would_refuse(r2_portal):
    c, *_ = r2_portal
    assert _links(c, [{"type": "image/jpeg", "size": 10}] * 5).status_code == 400                      # 5 photos
    assert _links(c, [{"type": "application/pdf", "size": 10}, {"type": "image/jpeg", "size": 10}]).status_code == 400
    assert _links(c, [{"type": "text/html", "size": 10}]).status_code == 400
    assert _links(c, [{"type": "image/jpeg", "size": 16 * 1024 * 1024}]).status_code == 400              # over 15 MB


def test_an_upload_from_another_patient_or_nowhere_is_refused(r2_portal):
    c, fake, plan, jpeg, _ = r2_portal
    fake.objects[("limber", "media/.incoming/attachments/P-018/0b1e6d0e-7b5d-4f36-9a35-0d1e5a7a2c11")] = jpeg()
    for key in (".incoming/attachments/P-018/0b1e6d0e-7b5d-4f36-9a35-0d1e5a7a2c11",
                ".incoming/attachments/P-017/0b1e6d0e-7b5d-4f36-9a35-0d1e5a7a2c11",      # never uploaded
                "P-017/attachments/../../secret"):
        r = c.post(f"/api/plans/{plan.id}/messages", headers={"Origin": "http://testserver"},
                   json={"text": "x", "uploaded": [key]})
        assert r.status_code == 400, (key, r.text)


def test_a_file_that_isnt_what_it_said_is_refused_and_removed(r2_portal):
    c, fake, plan, *_ = r2_portal
    link = _links(c, [{"type": "image/jpeg", "size": 20}]).json()["uploads"][0]
    _upload(fake, link, b"%PDF-1.4 not a photo")
    r = c.post(f"/api/plans/{plan.id}/messages", headers={"Origin": "http://testserver"},
               json={"text": "x", "uploaded": [link["key"]]})
    assert r.status_code == 400
    assert not [k for _, k in fake.objects if k.startswith("media/.incoming/")]


def test_every_accepted_recording_is_served_with_an_audio_or_video_type():
    """mp3, wav and mov were accepted by the probe but served as application/octet-stream, which some browsers
    won't play inline (found in slice B's live check; local installs too)."""
    from types import SimpleNamespace
    from interfaces.patient_portal import media_mime
    for ext in ("mp4", "mov", "webm", "m4a", "ogg", "mp3", "wav"):
        assert media_mime(SimpleNamespace(ext=ext)).split("/")[0] in ("audio", "video"), ext
