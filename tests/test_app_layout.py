"""The therapist app's layout from the design export: grouped sidebar, the Schedule page, and the patient page's
tabs. Streamlit AppTest, so no browser is needed."""

from datetime import date, timedelta

from streamlit.testing.v1 import AppTest

from src.assist import assistant
from src.portal import plans
from src.ptlog.store import SessionStore
from tests.test_app_pages import APP, seeded_env  # noqa: F401  (fixture)
from tests.test_app_plans import _seed


def _app(page, **state):
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.session_state["current_page"] = page
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def _text(at):
    return " ".join([x.value for x in at.text] + [x.value for x in at.markdown] + [c.value for c in at.caption] +
                    [w.value for w in at.warning] + [i.value for i in at.info])


class TestSidebar:
    def test_primary_items_then_tools_and_no_emoji(self, seeded_env):  # noqa: F811
        at = _app("home")
        assert not at.exception, [e.value for e in at.exception]
        keys = [b.key for b in at.button if b.key and b.key.startswith("nav_")]
        assert keys[:3] == ["nav_inbox", "nav_patients", "nav_schedule"]
        assert {"nav_live", "nav_video", "nav_sessions", "nav_obs_logs", "nav_review", "nav_tracker",
                "nav_learn", "nav_home"} <= set(keys)
        labels = [b.label for b in at.button if b.key and b.key.startswith("nav_")]
        assert all(label.isascii() for label in labels), labels
        assert at.selectbox(key="patient_select").label == "Find a patient"

    def test_the_current_page_is_marked(self, seeded_env):  # noqa: F811
        at = _app("home")
        at.button(key="nav_schedule").click().run()
        assert at.session_state["current_page"] == "schedule"
        assert at.button(key="nav_schedule").proto.type == "secondary"
        assert at.button(key="nav_inbox").proto.type == "tertiary"


class TestSchedule:
    def test_caseload_visits_with_the_request_first(self, seeded_env):  # noqa: F811
        knee, _, flagged = _seed(seeded_env)
        with SessionStore(seeded_env).open() as s:
            later = plans.schedule(s, "P-021", (date.today() + timedelta(days=12)).isoformat() + "T14:00", 30,
                                   "Strength check", plan_id=knee.id)
            plans.cancel(s, later.id)
        at = _app("schedule")
        assert not at.exception, [e.value for e in at.exception]
        text = _text(at)
        assert "P-021 asked to reschedule" in text and "Afternoons are better" in text
        upcoming = at.dataframe[0].value
        assert list(upcoming["Patient"]) == ["P-021"] and list(upcoming["Status"]) == ["Reschedule requested"]
        assert "Right knee, post-op" in list(upcoming["Plan"])
        assert any("Strength check" in str(f.value.to_dict()) for f in at.dataframe)   # cancelled, in the expander
        at.button(key=f"sched_open_{flagged.id}").click().run()
        assert at.session_state["current_page"] == "patients"
        assert at.session_state["patients_edit_select"] == "P-021"

    def test_empty(self, seeded_env):  # noqa: F811
        at = _app("schedule")
        assert not at.exception and any("No upcoming visits" in i.value for i in at.info)


class TestPatientTabs:
    def test_tabs_and_metrics_without_a_key(self, seeded_env):  # noqa: F811
        _seed(seeded_env)
        at = _app("patients", patients_edit_select="P-021")
        assert not at.exception, [e.value for e in at.exception]
        assert [t.label for t in at.tabs] == ["Overview", "Exercises", "Messages", "Session notes", "Details"]
        metrics = {m.label: m.value for m in at.metric}
        assert set(metrics) >= {"Days done, last 7", "Pain, latest", "Next visit"}
        assert metrics["Next visit"] != "None booked"
        assert "Right knee, post-op" in _text(at)                  # the header line names the active plan

    def test_the_ai_settings_tab_appears_with_a_key(self, seeded_env, monkeypatch):  # noqa: F811
        monkeypatch.setenv("LIMBER_ANTHROPIC_API_KEY", "sk-test-not-real")
        _seed(seeded_env)
        with SessionStore(seeded_env).open() as s:
            assistant.set_switch(s, "P-021", "summaries", True)
        at = _app("patients", patients_edit_select="P-021")
        assert not at.exception, [e.value for e in at.exception]
        assert "AI settings" in [t.label for t in at.tabs]
        assert at.toggle(key="assist_sw_summaries_P-021").value is True

    def test_messages_tab_opens_the_conversation(self, seeded_env):  # noqa: F811
        _seed(seeded_env)
        at = _app("patients", patients_edit_select="P-021")
        at.button(key="patient_to_inbox_P-021").click().run()
        assert at.session_state["current_page"] == "inbox" and at.session_state["inbox_open"] == "P-021"
