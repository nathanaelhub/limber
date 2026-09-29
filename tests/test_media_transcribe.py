"""Feature 014 T016 — writing out a voice note, driven by a fake transcriber.

No model weights and no speech library are involved anywhere here (constitution IV). The real
transcriber is a subprocess, so what is tested of it is the command it would run and its refusals; what
is tested of the queue is everything, with fakes standing in for the model.
"""

import hashlib
from datetime import datetime

import pytest

from src.media import transcribe
from src.portal import messages, uploads, voice
from src.ptlog.store import SessionStore
from tests.fixtures import media as fx

NOW = datetime(2026, 9, 28, 9, 0, 0)
SAID = "my knee catches on the stairs and it hurts at night"


@pytest.fixture
def env(tmp_db, tmp_path):
    from tests.conftest import FakeClock
    with SessionStore(tmp_db, clock=FakeClock(NOW)).open() as store:
        store.add_patient("P-017")
        messages.set_enabled(store, "P-017", True)
        note = fx.make_audio(tmp_path / "note.m4a", seconds=2.0)
        yield store, store.media_dir, note


def send(store, media_dir, note, patient="P-017"):
    data = note.read_bytes()
    up = uploads.begin(store, media_dir, patient, "voice", len(data), hashlib.sha256(data).hexdigest(),
                       chunk_bytes=len(data))
    uploads.put_part(store, media_dir, patient, up.id, 0, data)
    return voice.finish(store, media_dir, patient, up.id)


def fake(text=SAID, seconds=0.2):
    """A transcriber is just a callable from a path to text."""
    def transcriber(path):
        assert path.is_file(), "the worker must hand over a real file"
        return text
    transcriber.model_name = "fake-small"
    transcriber.seconds = seconds
    return transcriber


class TestAvailability:
    def test_not_available_without_a_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv(transcribe.MODEL_DIR_ENV, str(tmp_path / "nothing"))
        assert transcribe.model_installed() is False
        assert transcribe.available() is False
        # In this repository the library is absent too, and that is the first thing missing. Whichever it
        # is, the sentence has to name it, because it is shown to the therapist and in the health check.
        assert "library" in transcribe.why_not()
        monkeypatch.setattr(transcribe, "library_installed", lambda: True)
        assert transcribe.available() is False and "model" in transcribe.why_not()

    def test_a_directory_missing_a_file_is_not_a_model(self, tmp_path, monkeypatch):
        folder = tmp_path / "speech"
        folder.mkdir()
        (folder / "model.bin").write_bytes(b"not really")
        monkeypatch.setenv(transcribe.MODEL_DIR_ENV, str(folder))
        assert transcribe.model_installed() is False
        for name in transcribe.REQUIRED_FILES:
            (folder / name).write_text("{}")
        assert transcribe.model_installed() is True
        # the library is still absent in this repository, so the whole thing stays unavailable
        assert transcribe.available() is (transcribe.library_installed() and True)

    def test_nothing_is_queued_when_it_is_not_available(self, env, monkeypatch, tmp_path):
        store, media_dir, note = env
        monkeypatch.setenv(transcribe.MODEL_DIR_ENV, str(tmp_path / "nothing"))
        media = send(store, media_dir, note)
        assert store.transcription_for(media.id) is None
        assert store.transcriptions_waiting() == []
        assert transcribe.run_queue(store, media_dir, transcriber=fake()) == {"done": 0, "failed": 0}


class TestTheQueue:
    def test_a_note_is_queued_when_a_model_is_installed(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        media = send(store, media_dir, note)
        job = store.transcription_for(media.id)
        assert job is not None and job.state == "queued"

    def test_one_job_at_a_time_from_queued_to_done(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        first = send(store, media_dir, note)
        second = send(store, media_dir, note)
        assert len(store.transcriptions_waiting()) == 2
        one = transcribe.run_one(store, media_dir, transcriber=fake())
        assert one.media_id == first.id and one.state == "done" and one.text == SAID
        assert one.model == "fake-small" and one.seconds is not None and one.attempts == 1
        assert [j.media_id for j in store.transcriptions_waiting()] == [second.id]
        assert transcribe.run_queue(store, media_dir, transcriber=fake()) == {"done": 1, "failed": 0}
        assert store.transcriptions_waiting() == []
        assert transcribe.run_one(store, media_dir, transcriber=fake()) is None      # nothing left to do

    def test_a_transcript_that_looks_identifying_is_marked(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        media = send(store, media_dir, note)
        job = transcribe.run_one(store, media_dir, transcriber=fake("I saw Doctor Jane Smith on Tuesday"))
        assert job.state == "done" and job.warned is True and "Jane Smith" in job.text
        assert store.transcription_for(media.id).warned is True

    def test_nothing_recognisable_is_not_a_failure(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        send(store, media_dir, note)
        job = transcribe.run_one(store, media_dir, transcriber=fake("   "))
        assert job.state == "done" and job.text == "" and job.warned is False

    @pytest.mark.parametrize("error, reason", [
        (transcribe.TranscriberTimeout("too slow"), "timeout"),
        (transcribe.Unreadable("cannot decode"), "unreadable"),
        (transcribe.NotInstalled("no library"), "not_installed"),
        (RuntimeError("something else"), "error"),
    ])
    def test_a_failure_keeps_a_reason_word_and_the_recording(self, env, monkeypatch, error, reason):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        media = send(store, media_dir, note)

        def angry(path):
            raise error
        angry.model_name = "fake-small"
        job = transcribe.run_one(store, media_dir, transcriber=angry)
        assert job.state == "failed" and job.reason == reason and job.text is None
        assert uploads.media_path(media_dir, store.media_get(media.id)).is_file()   # the audio is untouched
        assert "something else" not in str(job.reason)                             # a word, not a message

    def test_a_failed_job_is_not_retried_for_ever(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        send(store, media_dir, note)

        def angry(path):
            raise RuntimeError("no")
        angry.model_name = "fake-small"
        transcribe.run_one(store, media_dir, transcriber=angry)
        assert store.transcriptions_waiting() == []                                # failed is not queued
        assert transcribe.retry(store, store.transcription_for(store.media_list("P-017", "voice")[0].id).id) is True
        assert len(store.transcriptions_waiting()) == 1
        transcribe.run_one(store, media_dir, transcriber=angry)
        job = store.transcription_for(store.media_list("P-017", "voice")[0].id)
        assert job.attempts == 2 and job.state == "failed"
        assert transcribe.retry(store, job.id) is False                            # two attempts is enough

    def test_a_deleted_recording_takes_its_job_with_it(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        media = send(store, media_dir, note)
        assert voice.delete(store, media_dir, "P-017", media.id, by="patient") is True
        assert store.transcription_for(media.id) is None
        assert transcribe.run_one(store, media_dir, transcriber=fake()) is None

    def test_a_job_whose_file_has_gone_fails_rather_than_crashing(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        media = send(store, media_dir, note)
        uploads.media_path(media_dir, media).unlink()
        job = transcribe.run_one(store, media_dir, transcriber=fake())
        assert job.state == "failed" and job.reason == "missing"


class TestTheRealTranscriberWithoutInstalling:
    """What can honestly be checked about the subprocess path with no library and no weights present."""

    def test_it_refuses_plainly_when_nothing_is_installed(self, env, tmp_path, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setenv(transcribe.MODEL_DIR_ENV, str(tmp_path / "nothing"))
        with pytest.raises(transcribe.NotInstalled) as err:
            transcribe.load()
        assert "not installed" in str(err.value).lower() or "no speech model" in str(err.value).lower()

    def test_the_command_it_would_run_is_this_repository_and_nothing_else(self):
        args = transcribe.worker_command()
        assert args[0].endswith("python") or "python" in args[0]
        assert args[1:3] == ["-m", "src.media.transcribe"]         # our own module, no shell, no network

    def test_the_subprocess_transcriber_reports_a_timeout_as_one(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "worker_command", lambda: ["/bin/sh", "-c", "sleep 5"])
        runner = transcribe.subprocess_transcriber(timeout=0.4)
        with pytest.raises(transcribe.TranscriberTimeout):
            runner(note)

    def test_the_subprocess_transcriber_passes_the_text_back(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "worker_command",
                            lambda: ["/bin/sh", "-c", 'printf \'{"text": "said this"}\'; exit 0'])
        runner = transcribe.subprocess_transcriber(timeout=5)
        assert runner(note) == "said this"

    def test_the_worker_saying_nothing_is_installed_is_reported_as_that(self, env, monkeypatch):
        """Exit code 3 is the worker's way of saying the library or model is missing. Reporting that as
        "unreadable" would blame the patient's recording for the host's missing setup."""
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        send(store, media_dir, note)
        monkeypatch.setattr(transcribe, "worker_command",
                            lambda: ["/bin/sh", "-c", 'echo "no library" >&2; exit 3'])
        job = transcribe.run_one(store, media_dir)
        assert job.state == "failed" and job.reason == "not_installed"

    def test_a_worker_that_dies_is_a_failure_not_a_crash(self, env, monkeypatch):
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "worker_command", lambda: ["/bin/sh", "-c", "exit 9"])
        runner = transcribe.subprocess_transcriber(timeout=5)
        with pytest.raises(transcribe.Unreadable):
            runner(note)


class TestWhatTheInstallationSaysAboutIt:
    """Feature 014 T020 — the transcript is the therapist's, and an installation without one says so."""

    def test_the_health_check_reports_it_as_optional(self, tmp_db, tmp_path, monkeypatch):
        from src.deploy import preflight
        monkeypatch.setenv(transcribe.MODEL_DIR_ENV, str(tmp_path / "nothing"))
        checks = {c.name: c for c in preflight.run(tmp_db, tmp_path, "https://l.example.org",
                                                   "https://l.example.org/therapist")}
        speech = checks["speech_model"]
        assert speech.optional is True and speech.ok is False
        assert "voice notes still" in speech.detail or "not available" in speech.detail
        assert [c for c in checks.values() if not c.ok and not c.optional], "the other checks still gate"

    def test_the_patient_never_sees_a_transcript(self, env, monkeypatch, tmp_db):
        from starlette.testclient import TestClient
        from interfaces.patient_portal import create_app
        from src.portal import access
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        media = send(store, media_dir, note)
        transcribe.run_one(store, media_dir, transcriber=fake("I told them about my sore knee"))
        code = access.issue_code(store, b"k" * 32, "P-017")[0]
        app = create_app(db_path=tmp_db, key=b"k" * 32, allowed_origins=["http://testserver"])
        with TestClient(app, base_url="http://testserver") as c:
            c.post("/api/login", json={"code": code}, headers={"Origin": "http://testserver"})
            for route in ("/api/messages", "/api/media", f"/api/media?kind=voice", "/api/today", "/voice", "/messages"):
                text = c.get(route).text
                assert "sore knee" not in text, route
                assert "transcript" not in text.lower(), route
            assert c.get(f"/api/media/{media.id}").status_code == 200      # they can still hear it

    def test_the_service_health_says_whether_it_can_write_out(self, env, tmp_db, monkeypatch, tmp_path):
        from starlette.testclient import TestClient
        from interfaces.patient_portal import create_app
        monkeypatch.setenv(transcribe.MODEL_DIR_ENV, str(tmp_path / "nothing"))
        app = create_app(db_path=tmp_db, key=b"k" * 32, allowed_origins=["http://testserver"])
        with TestClient(app, base_url="http://testserver") as c:
            body = c.get("/api/health").json()
        assert body["ok"] is True and body["voice_transcripts"] is False    # optional, and not a failure

    def test_the_queue_can_be_worked_from_outside_the_service(self, env, monkeypatch):
        """What the CLI does is `run_queue`; the command itself is exercised in tests/test_cli_portal.py,
        where it runs as a real process on an installation with no model."""
        store, media_dir, note = env
        monkeypatch.setattr(transcribe, "available", lambda *a, **k: True)
        send(store, media_dir, note)
        assert transcribe.run_queue(store, media_dir, transcriber=fake("said something")) == {"done": 1, "failed": 0}
        listed = [(j.state, j.model) for j in [store.transcription_for(store.media_list("P-017", "voice")[0].id)]]
        assert listed == [("done", "fake-small")]
