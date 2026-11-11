"""Feature 020 slice D, gate E (option a, the owner's choice): the patient portal can run without torch, Ultralytics,
or Streamlit, which Vercel's Python functions can't hold. The engine loads Ultralytics only when a model is created."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HEAVY = ("ultralytics", "torch", "torchvision", "streamlit", "streamlit_webrtc")


def _loaded_by(statement: str):
    out = subprocess.run([sys.executable, "-c", f"import sys; {statement}; "
                          f"print(','.join(m for m in {HEAVY!r} if m in sys.modules))"],
                         cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    lines = out.stdout.rstrip("\n").split("\n")
    return [m for m in lines[-1].split(",") if m]                    # the last line lists what was loaded


def test_the_patient_portal_loads_no_heavy_library():
    assert _loaded_by("import interfaces.patient_portal") == []


def test_the_engine_itself_imports_without_ultralytics():
    assert _loaded_by("import analyze") == []


def test_creating_a_model_still_uses_ultralytics(monkeypatch):
    import analyze
    made = []

    class FakeYOLO:
        def __init__(self, path):
            made.append(path)
    import ultralytics
    monkeypatch.setattr(ultralytics, "YOLO", FakeYOLO)
    analyze.YOLO("models/yolo11m-pose.pt")
    assert made == ["models/yolo11m-pose.pt"]


# ---- the Vercel entry point (T024) ------------------------------------------------------------------------------

HOSTED = {"TURSO_DATABASE_URL": "libsql://demo.example", "TURSO_AUTH_TOKEN": "t", "LIMBER_DEMO": "1",
          "LIMBER_PUBLIC_ORIGIN": "https://limber-demo.vercel.app", "PTASSIST_PORTAL_KEY": "ab" * 32,
          "LIMBER_R2_ACCOUNT_ID": "acct", "LIMBER_R2_BUCKET": "limber", "LIMBER_R2_ACCESS_KEY_ID": "id",
          "LIMBER_R2_SECRET_ACCESS_KEY": "secret"}


def test_the_vercel_app_refuses_to_start_without_its_settings():
    import pytest
    from interfaces import vercel_app
    for missing in ("TURSO_DATABASE_URL", "LIMBER_DEMO", "LIMBER_PUBLIC_ORIGIN", "PTASSIST_PORTAL_KEY", "LIMBER_R2_BUCKET"):
        env = {k: v for k, v in HOSTED.items() if k != missing}
        with pytest.raises(RuntimeError, match=missing):
            vercel_app.check_settings(env)
    vercel_app.check_settings(HOSTED)


def test_the_therapist_door_explains_what_is_online(monkeypatch, tmp_path):
    from starlette.testclient import TestClient
    from interfaces import vercel_app
    monkeypatch.setenv("LIMBER_DB_BACKEND", "libsql")
    app = vercel_app.build(tmp_path / "replica.db", "https://limber-demo.vercel.app", key=b"k" * 32)
    page = TestClient(app, base_url="https://limber-demo.vercel.app").get("/therapist?pass=abc")
    assert page.status_code == 200 and "runs on the clinic's own computer" in " ".join(page.text.split())
    assert "pass=abc" not in page.text
    assert page.headers["content-security-policy"].startswith("default-src 'self'")


def test_the_vercel_bundle_is_light():
    """deploy/vercel/requirements.txt is what Vercel installs: no torch, Ultralytics, Streamlit, or desktop OpenCV."""
    names = [line.split(">=")[0].split("==")[0].strip().lower()
             for line in (REPO / "deploy" / "vercel" / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    for heavy in ("torch", "torchvision", "ultralytics", "streamlit", "streamlit-webrtc", "opencv-python"):
        assert heavy not in names, heavy
    for needed in ("starlette", "python-multipart", "numpy", "opencv-python-headless", "pillow", "pyyaml", "av",
                   "anthropic", "libsql", "boto3"):
        assert needed in names, needed
