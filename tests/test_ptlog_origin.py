"""Feature 007 T018 — capture origin (clinic or home) and the rule that numbers are never compared
across origins (FR-020, SC-009). The browser's pose model measures range of motion differently from
the clinic's (research D2), so a mixed series would raise false flags or show fake progress."""

import json
from datetime import datetime, timedelta

import pytest

from src.ptlog import measures, review, tracker
from src.ptlog.models import ComparisonError
from src.ptlog.origin import CLINIC, HOME, capture_origin

D0 = datetime(2026, 3, 23, 9, 15, 0)


def mark_home(store, session_id):
    """What the patient portal's sessions look like: source webcam, origin portal."""
    store.conn.execute("UPDATE sessions SET source = 'webcam', source_ref = 'home', source_extras = ? WHERE id = ?",
                       (json.dumps({"origin": "portal", "pose_model": "movenet-lightning-4", "fps_nominal": 15}), session_id))
    store.conn.commit()


@pytest.fixture
def mixed(fixed_store, make_session):
    """Four clinic sessions at about 85 degrees, then four home sessions reading 12 degrees higher."""
    store, clock = fixed_store
    store.add_patient("P-017")
    clinic = [make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=d), [(90.0, rom, 2.4)] * 2, target_reps=2)
              for d, rom in zip((20, 18, 16, 14), (84.0, 85.0, 86.0, 85.0))]
    home = [make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=d), [(90.0, rom, 2.4)] * 2, target_reps=2)
            for d, rom in zip((12, 10, 8, 6), (97.0, 98.0, 97.5, 98.0))]
    for sid in home:
        mark_home(store, sid)
    return store, clock, clinic, home


class TestOrigin:
    def test_capture_origin(self, mixed):
        store, _, clinic, home = mixed
        assert capture_origin(store.load_session(clinic[0])) == CLINIC == "clinic"
        assert capture_origin(store.load_session(home[0])) == HOME == "home"

    def test_web_live_sessions_in_the_clinic_stay_clinic(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-030")
        sid = make_session(store, clock, "P-030", "Squat", D0, [(90.0, 80.0, 2.4)])
        store.conn.execute("UPDATE sessions SET source_extras = ? WHERE id = ?", (json.dumps({"origin": "web"}), sid))
        store.conn.commit()
        assert capture_origin(store.load_session(sid)) == "clinic"

    def test_measures_carry_the_origin(self, mixed):
        store, _, clinic, home = mixed
        assert measures.measures_for_session(store.load_session(home[0]))["Knee Extension"].origin == "home"
        assert measures.measures_for_session(store.load_session(clinic[0]))["Knee Extension"].origin == "clinic"


class TestNoMixing:
    def test_trend_is_split_by_origin(self, mixed):
        store, *_ = mixed
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0)
        assert [m.origin for m in t.points] == ["clinic"] * 4 + ["home"] * 4
        assert set(t.by_origin) == {"clinic", "home"}
        assert t.by_origin["clinic"].summary["avg_rom"]["change"] == pytest.approx(1.0)
        assert t.by_origin["home"].summary["avg_rom"]["change"] == pytest.approx(1.0)
        assert t.primary_origin == "home"                                  # the latest session's origin
        assert t.summary == t.by_origin["home"].summary                     # never first-clinic to latest-home (+14)

    def test_no_flag_is_raised_across_origins(self, mixed, make_session):
        store, clock, clinic, home = mixed
        assert [f.rule for f in review.flags_for(store, "P-017", "all", now=D0 - timedelta(days=5)).flags] == []
        # a clinic visit after the home block reads 12 degrees "lower" than home: still no regression
        make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=4), [(90.0, 85.5, 2.4)] * 2, target_reps=2)
        assert [f.rule for f in review.flags_for(store, "P-017", "all", now=D0 - timedelta(days=3)).flags] == []

    def test_a_real_regression_inside_one_origin_is_still_flagged_and_says_where(self, mixed, make_session):
        store, clock, _, _ = mixed
        sid = make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=4), [(90.0, 86.0, 2.4)] * 2, target_reps=2)
        mark_home(store, sid)                                                # home: 97, 98, 97.5, 98, then 86
        result = review.flags_for(store, "P-017", "all", now=D0 - timedelta(days=3))
        (flag,) = [f for f in result.flags if f.rule == "rom_regression"]
        assert flag.values["origin"] == "home" and "home sessions" in flag.message and sid in flag.session_ids

    def test_each_origin_needs_its_own_minimum(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-031")
        for i, d in enumerate((10, 8, 6, 4)):
            sid = make_session(store, clock, "P-031", "Squat", D0 - timedelta(days=d), [(90.0, 90.0 - 6 * i, 2.4)], target_reps=1)
            if i % 2:
                mark_home(store, sid)
        result = review.flags_for(store, "P-031", "all", now=D0 - timedelta(days=3))
        assert result.flags == []
        waiting = {(n.rule, n.exercise, n.have) for n in result.not_evaluated}
        assert ("rom_regression", "Squat", 2) in waiting and ("rom_regression", "Squat (home)", 2) in waiting

    def test_counts_use_all_sessions(self, mixed):
        store, *_ = mixed
        store.assign_program("P-017", "custom", "Knee", ["knee_extension"], 2, (D0 - timedelta(days=21)).date())
        row = {r.patient_id: r for r in tracker.roster(store, now=D0 - timedelta(days=5))}["P-017"]
        assert row.sessions_30d == 8 and row.pending_reviews == 8 and row.adherence_pct is not None
        assert row.practice_gap is False                                    # home sessions count as practice

    def test_comparing_across_origins_is_refused(self, mixed):
        store, _, clinic, home = mixed
        with pytest.raises(ComparisonError) as err:
            review.compare(store, clinic[0], home[0])
        assert "home" in str(err.value) and "clinic" in str(err.value)
        assert review.compare(store, home[0], home[1]).exercise == "Knee Extension"

    def test_goal_progress_uses_one_origin(self, mixed):
        store, *_ = mixed
        store.set_goal("P-017", "Knee Extension", target_rom=100.0)
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0)
        assert t.by_origin["clinic"].rom_progress_pct != t.by_origin["home"].rom_progress_pct
        assert t.rom_progress_pct == t.by_origin["home"].rom_progress_pct


class TestClinicOnlyIsUnchanged:
    def test_single_origin_trend_has_the_same_top_level_fields(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-032")
        for d, rom in zip((9, 6, 3), (80.0, 84.0, 88.0)):
            make_session(store, clock, "P-032", "Squat", D0 - timedelta(days=d), [(90.0, rom, 2.4)])
        t = review.trend(store, "P-032", "Squat", "all", now=D0)
        assert list(t.by_origin) == ["clinic"] and t.primary_origin == "clinic"
        assert t.summary["avg_rom"] == {"first": 80.0, "latest": 88.0, "change": 8.0} and t.enough_for_trend
        assert t.summary == t.by_origin["clinic"].summary


class TestShownToTheTherapist:
    """FR-020: every place that lists sessions says where each was recorded."""

    def test_session_list_and_trend_rows_carry_the_origin(self, mixed):
        from src.ptlog import views
        store, _, clinic, home = mixed
        rows = {r["id"]: r for r in views.session_table_rows(store, "P-017")}
        assert rows[home[0]]["origin"] == "home" and rows[clinic[0]]["origin"] == "clinic"
        t = review.trend(store, "P-017", "Knee Extension", "all", now=D0)
        assert [r["origin"] for r in views.trend_table_rows(t)] == ["clinic"] * 4 + ["home"] * 4

    def test_trend_summary_is_printed_per_origin_when_mixed(self, mixed):
        from src.ptlog import views
        store, *_ = mixed
        lines = views.trend_summary_lines(review.trend(store, "P-017", "Knee Extension", "all", now=D0))
        text = "\n".join(lines)
        assert "Clinic sessions" in text and "Home sessions" in text and "not compared" in text
        assert "84.0° → 85.0°" in text and "97.0° → 98.0°" in text and "84.0° → 98.0°" not in text

    def test_review_report_and_csv(self, mixed):
        from src.ptlog.exports.review_csv import to_review_csv
        from src.ptlog.exports.review_report import to_review_report
        store, _, clinic, home = mixed
        summary = review.review_summary(store, "P-017", "all", now=D0)
        report = to_review_report(summary)
        assert "Knee Extension — 4 clinic sessions" in report and "Knee Extension — 4 home sessions" in report
        assert "avg ROM +14" not in report
        rows = to_review_csv(summary).strip().split("\r\n")
        header = rows[0].split(",")
        assert header[-1] == "recorded"
        assert {r.rsplit(",", 1)[1] for r in rows[1:]} == {"clinic", "home"}


# ----------------------------------------------------------------------------- feature 012: self-reported

def make_diary(store, patient, name, key, when, reps=10, sets=1, effort=3):
    from src.ptlog.models import ExerciseSetInfo
    sid = store.start_session(patient, "diary", "self-reported", {"origin": "diary"})
    store.conn.execute("UPDATE sessions SET start_time = ? WHERE id = ?", (when.isoformat(), sid))
    set_id = store.open_set(sid, ExerciseSetInfo(key, name, "left", 10, 170.0, 90.0))
    store.set_reported(set_id, reps=reps, sets=sets, effort=effort)
    store.conn.commit()
    store.end_session(sid)
    return sid


class TestDiaryOrigin:
    def test_origin_and_labels(self, fixed_store, make_session):
        from src.ptlog import views
        store, clock = fixed_store
        store.add_patient("P-040")
        clinic = make_session(store, clock, "P-040", "Squat", D0 - timedelta(days=3), [(90.0, 80.0, 2.4)])
        diary = make_diary(store, "P-040", "Squat", "squat", D0 - timedelta(days=1))
        assert capture_origin(store.load_session(diary)) == "self-reported"
        rows = {r["id"]: r for r in views.session_table_rows(store, "P-040")}
        assert rows[diary]["origin"] == "self-reported" and rows[clinic]["origin"] == "clinic"
        stored = store.load_session(diary)
        assert stored.total_reps == 10 and stored.avg_rom is None and stored.avg_form_score is None

    def test_counted_as_practice_but_never_measured(self, fixed_store, make_session):
        from src.ptlog import review, tracker
        from src.portal import viewmodels as vm
        store, clock = fixed_store
        store.add_patient("P-041")
        store.assign_program("P-041", "custom", "Home", ["squat"], 2, (D0 - timedelta(days=21)).date())
        for d in (9, 7, 2, 1):
            make_diary(store, "P-041", "Squat", "squat", D0 - timedelta(days=d))
        make_diary(store, "P-041", "Squat", "squat", D0 - timedelta(hours=2))        # inside the week in progress
        row = {r.patient_id: r for r in tracker.roster(store, now=D0)}["P-041"]
        assert row.sessions_30d == 5 and row.adherence_pct is not None and row.practice_gap is False
        assert vm.today_view(store, "P-041", now=D0)["week"]["done"] >= 1
        assert vm.adherence_view(store, "P-041", now=D0)["streak_weeks"] >= 1
        t = review.trend(store, "P-041", "Squat", "all", now=D0)
        assert t.points == [] and t.by_origin == {}                     # nothing measured to compare
        assert review.flags_for(store, "P-041", "all", now=D0).flags == []

    def test_done_today_and_comparison(self, fixed_store, make_session):
        from src.ptlog import review
        from src.portal import viewmodels as vm
        from src.ptlog.models import ComparisonError
        store, clock = fixed_store
        store.add_patient("P-042")
        store.assign_program("P-042", "custom", "Home", ["squat"], 2, (D0 - timedelta(days=21)).date())
        diary = make_diary(store, "P-042", "Squat", "squat", D0 - timedelta(hours=2))
        assert vm.today_view(store, "P-042", now=D0)["exercises"][0]["done_today"] is True
        clinic = make_session(store, clock, "P-042", "Squat", D0 - timedelta(days=4), [(90.0, 80.0, 2.4)])
        with pytest.raises(ComparisonError):
            review.compare(store, clinic, diary)

    def test_a_trend_with_only_logged_sessions_says_how_many(self, fixed_store, make_session):
        """The trend view must not say "no sessions" when the patient logged some: they happened, they
        just carry nothing to measure (feature 012 FR-003, FR-004)."""
        from src.ptlog import review as ptreview
        store, clock = fixed_store
        store.add_patient("P-042")
        for d in (5, 2):
            make_diary(store, "P-042", "Squat", "squat", D0 - timedelta(days=d))
        make_session(store, clock, "P-042", "Knee Extension", D0 - timedelta(days=4), [(90.0, 80.0, 2.4)])
        assert ptreview.trend(store, "P-042", "Squat", "30d", now=D0).points == []
        assert ptreview.self_reported_count(store, "P-042", "Squat", "30d", now=D0) == 2
        # the period is a start, not a window: eleven days on, only the later one is still inside 14 days
        assert ptreview.self_reported_count(store, "P-042", "Squat", "14d", now=D0 + timedelta(days=11)) == 1
        assert ptreview.self_reported_count(store, "P-042", "Knee Extension", "30d", now=D0) == 0
        assert "Squat" in ptreview.exercise_names(store, "P-042")
