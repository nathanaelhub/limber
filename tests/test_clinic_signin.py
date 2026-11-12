"""Feature 019 slice 1 (T006, T008): signing in to the clinic app.

Staff reach the clinic by the portal's Therapist door (a single-use pass) or by the clinic's own sign-in form.
The sign-in is the `limber_staff` cookie, scoped to /therapist, and it survives a reload but not its lifetime."""

from src.portal import admin
from src.ptlog.store import SessionStore
from tests.clinic_helpers import H, PASSWORD, client, seed, sign_in


def _pass(db, clock, username="therapist"):
    with SessionStore(db, clock=clock).open() as store:
        return admin.issue_pass(store, store.account_by_username(username).id, clock=clock)


def test_pages_send_a_visitor_to_sign_in_and_keep_where_they_were_going(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        r = c.get("/therapist/settings", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/therapist/signin?next=/therapist/settings"
        assert c.get("/therapist/api/me").status_code == 401
        assert c.get("/therapist/api/me").json()["signed_out"] is True


def test_the_pass_signs_in_once_and_leaves_the_address(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    a_pass = _pass(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        r = c.get(f"/therapist/?pass={a_pass}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/therapist/dashboard"      # the pass is gone
        assert c.get("/therapist/api/me").json()["username"] == "therapist"
    with client(tmp_db, fake_clock) as other:
        r = other.get(f"/therapist/?pass={a_pass}", follow_redirects=False)                  # used once already
        assert r.headers["location"] == "/therapist/signin?expired=1"
        assert other.get("/therapist/api/me").status_code == 401


def test_the_pass_can_carry_a_safe_next_page_only(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        r = c.get(f"/therapist/?pass={_pass(tmp_db, fake_clock)}&next=/therapist/settings", follow_redirects=False)
        assert r.headers["location"] == "/therapist/settings"
    with client(tmp_db, fake_clock) as c:
        r = c.get(f"/therapist/?pass={_pass(tmp_db, fake_clock)}&next=//evil.example/x", follow_redirects=False)
        assert r.headers["location"] == "/therapist/dashboard"


def test_an_old_pass_does_not_sign_in(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    a_pass = _pass(tmp_db, fake_clock)
    fake_clock.advance(admin.PASS_LIFETIME.total_seconds() + 1)
    with client(tmp_db, fake_clock) as c:
        assert c.get(f"/therapist/?pass={a_pass}", follow_redirects=False).headers["location"].endswith("expired=1")


def test_the_cookie_is_locked_down(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock, secure=True, base="https://testserver") as c:
        r = c.post("/therapist/api/login", json={"username": "therapist", "password": PASSWORD},
                   headers={"Origin": "http://testserver"})
        cookie = r.headers["set-cookie"].lower()
        assert cookie.startswith("limber_staff=")
        for part in ("httponly", "samesite=strict", "secure", "path=/therapist", "max-age=28800"):
            assert part in cookie, part


def test_reload_keeps_the_sign_in_until_it_runs_out(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        assert c.get("/therapist/settings").status_code == 200
        assert c.get("/therapist/settings").status_code == 200                              # a reload
        fake_clock.advance(admin.SIGN_IN_LIFETIME.total_seconds() + 1)
        assert c.get("/therapist/settings", follow_redirects=False).status_code == 303


def test_the_sign_in_form(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        page = c.get("/therapist/signin")
        assert page.status_code == 200 and "data-signin" in page.text
        r = c.post("/therapist/api/login", json={"username": "therapist", "password": "wrong password"}, headers=H)
        assert r.status_code == 401 and "did not work" in r.json()["error"]
        r = c.post("/therapist/api/login", json={"username": "rivera", "password": PASSWORD,
                                                 "next": "/therapist/settings"}, headers=H)
        assert r.json() == {"redirect": "/therapist/settings"}
        assert c.get("/therapist/signin", follow_redirects=False).status_code == 303      # already signed in


def test_a_patient_account_cannot_sign_in_here(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with SessionStore(tmp_db, clock=fake_clock).open() as store:
        from src.portal import accounts
        accounts.create_account(store, username="pat", display_name="Pat", password=PASSWORD, role="patient",
                                patient_id="P-001")
    with client(tmp_db, fake_clock) as c:
        r = c.post("/therapist/api/login", json={"username": "pat", "password": PASSWORD}, headers=H)
        assert r.status_code == 401


def test_repeated_failures_lock_the_form(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        codes = [c.post("/therapist/api/login", json={"username": "therapist", "password": "nope nope nope"},
                        headers=H).status_code for _ in range(12)]
        assert codes[-1] == 429 and 401 in codes
        assert c.post("/therapist/api/login", json={"username": "therapist", "password": PASSWORD},
                      headers=H).status_code == 429


def test_sign_out_ends_the_sign_in(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        token = c.cookies.get("limber_staff")
        assert c.post("/therapist/api/logout", json={}, headers=H).status_code == 200
        c.cookies.set("limber_staff", token, path="/therapist")                             # an old copy
        assert c.get("/therapist/api/me").status_code == 401


def test_writes_need_the_clinic_page_and_json(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        assert c.post("/therapist/api/login", json={}, headers={"Origin": "https://elsewhere.example"}).status_code == 403
        r = c.post("/therapist/api/login", content="username=x", headers={**H, "Content-Type": "text/plain"})
        assert r.status_code == 415


def test_no_staff_password_shows_the_setup_message(tmp_db, fake_clock):
    with client(tmp_db, fake_clock) as c:
        page = c.get("/therapist/signin")
        assert "not set up" in page.text and "portal admin set-password" in page.text
        assert "data-signin" not in page.text
        r = c.post("/therapist/api/login", json={"username": "therapist", "password": PASSWORD}, headers=H)
        assert r.status_code == 409


def test_preferences_save_and_show_on_the_first_render(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        sign_in(c)
        r = c.post("/therapist/api/me/preferences", json={"larger_text": True, "high_contrast": True}, headers=H)
        assert r.json()["classes"] == "lt hc"
        page = c.get("/therapist/settings").text
        assert '<div class="lb app lt hc">' in page
        assert 'data-pref="larger_text" checked' in page and 'data-pref="reduced_motion">' in page
        assert c.get("/therapist/api/me/preferences").json()["prefs"]["high_contrast"] is True


def test_health_answers_without_sign_in(tmp_db, fake_clock):
    seed(tmp_db, fake_clock)
    with client(tmp_db, fake_clock) as c:
        assert c.get("/therapist/api/health").json() == {"ok": True, "record": "ok", "staff_sign_in": True}
