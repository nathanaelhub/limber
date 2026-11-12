"""Feature 019 slice 1 (T007, T008, FR-005): the clinic app's pages and files obey its content security policy.

No inline style or script (the policy blocks both, so they would silently not work), and nothing is loaded from
another site."""

import re
from pathlib import Path

from src.clinic import charts, shell
from tests.clinic_helpers import H, client, seed, sign_in

STATIC = Path(__file__).resolve().parent.parent / "interfaces" / "clinic_static"
OUTSIDE = re.compile(r"""(?:src|href|url)\s*[=(]\s*["']?(?:https?:)?//""", re.I)


def _checked(html: str, where: str):
    assert "style=" not in html, where
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), where              # no inline script
    assert not re.search(r"\son[a-z]+=", html), where                         # no inline handlers
    assert not OUTSIDE.search(html), where


def test_every_rendered_page_obeys_the_policy(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        _checked(c.get("/therapist/signin").text, "signin")
        sign_in(c)
        for route in c.app.state.registry:
            if route.kind == "page" and "GET" in route.methods and "{" not in route.path and route.path != "/therapist/":
                r = c.get(route.path)
                assert r.status_code == 200, route.path
                _checked(r.text, route.path)
                assert r.headers["cache-control"] == "no-store"
                csp = r.headers["content-security-policy"]
                assert "style-src 'self'" in csp and "unsafe-inline" not in csp


def test_the_setup_page_and_charts_obey_it_too():
    _checked(shell.sign_in(False), "setup")
    _checked(charts.render(charts.line_chart("Pain", [("Mon", 3), ("Tue", None), ("Wed", 4)])), "chart")


def test_static_files_load_nothing_from_outside():
    for f in STATIC.glob("*"):
        if f.suffix in (".css", ".js", ".html"):
            text = f.read_text()
            assert not OUTSIDE.search(text), f.name
            assert "@import" not in text, f.name
    assert (STATIC / "sora.woff2").stat().st_size > 1000


def test_the_stylesheet_keeps_hidden_hidden_and_scales_chart_text():
    css = (STATIC / "limber.css").read_text()
    assert "[hidden]{display:none!important}" in css
    assert ".chart text{font-size:calc(12px*var(--scale))" in css
    for mode in (".lb.lt{", ".lb.hc{", ".lb.lm"):
        assert mode in css


def test_static_files_are_served_with_the_headers(tmp_db, fake_clock):
    with client(tmp_db, fake_clock) as c:
        r = c.get("/therapist/static/limber.css")
        assert r.status_code == 200 and "content-security-policy" in r.headers
        assert c.get("/therapist/static/clinic.js").status_code == 200
