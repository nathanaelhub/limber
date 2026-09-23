"""Feature 010 T009 — the installable app: manifest, service worker, and what may be cached."""

import json
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from interfaces import patient_portal
from interfaces.patient_portal import create_app
from src.portal import pwa

KEY = b"k" * 32
ORIGIN = "http://testserver"


@pytest.fixture
def client(tmp_db):
    app = create_app(db_path=tmp_db, key=KEY, allowed_origins=[ORIGIN])
    with TestClient(app, base_url=ORIGIN) as c:
        yield c


def test_manifest_is_served_by_limber_with_its_icons(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["name"] == "Limber" and m["display"] == "standalone" and m["start_url"] == "/today" and m["scope"] == "/"
    assert m["theme_color"] == "#0E6B64" and m["background_color"] == "#FAF8F4"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in m["icons"]:
        assert icon["src"].startswith("/static/") and client.get(icon["src"]).headers["content-type"] == "image/png"
    assert "content-security-policy" in r.headers


def test_service_worker_is_at_the_root_and_never_caches_the_api(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith(("application/javascript", "text/javascript"))
    assert r.headers["cache-control"] == "no-store"
    js = r.text
    assert "/api/" in js and "networkOnly" in js or "never cache" in js.lower()
    assert "precache" in js and "CACHE_NAME" in js
    assert not re.findall(r"""["']https?://""", js)                          # nothing from other sites
    for word in ("rep_count", "form", "pain", "target"):                     # no clinical logic in the worker
        assert word not in js.lower() or word == "form" and "form_" not in js.lower()


def test_precache_lists_real_shell_files_only():
    entries = pwa.precache(patient_portal.STATIC_DIR)
    urls = [u for u, _ in entries]
    assert "/static/portal.css" in urls and "/static/portal.js" in urls and "/today" in urls and "/checkin" in urls
    assert not any(u.startswith("/api") or "vendor" in u or u == "/sw.js" for u in urls)
    for url, digest in entries:
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        if url.startswith("/static/"):
            assert (patient_portal.STATIC_DIR / url[len("/static/"):]).is_file()


def test_pages_link_the_manifest_and_show_an_install_hint(client):
    for page in ("index.html", "today.html", "checkin.html"):
        html = (patient_portal.STATIC_DIR / page).read_text()
        assert 'rel="manifest"' in html and 'apple-touch-icon' in html and 'apple-mobile-web-app-capable' in html
    today = (patient_portal.STATIC_DIR / "today.html").read_text()
    assert 'id="install-hint"' in today and "Add to Home Screen" in today
