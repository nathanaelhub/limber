"""Feature 003 — tracker: migration 3, models, store primitives, roster, adherence, queue."""

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from src.ptlog import models
from src.ptlog.models import (
    METRIC_DEFINITIONS,
    AssignmentValidationError,
    BuiltinPatientError,
    PatientNotFoundError,
    ProgramValidationError,
    PTLogError,
)
from src.ptlog.store import MIGRATIONS, SessionStore

D0 = datetime(2026, 3, 23, 9, 15, 0)
TODAY = date(2026, 3, 23)
KEYS = ["knee_extension", "knee_extension_right", "partial_squat", "seated_hip_flexion", "seated_hip_flexion_right"]


# ======================================================================================
# T003 — migration 3 and models
# ======================================================================================

class TestMigration3:
    def test_v2_database_upgrades_to_v3(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        for version, sql in MIGRATIONS[:2]:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, '2026-01-01T00:00:00')", (version,))
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('unassigned', 'Unassigned', NULL, '2026-01-01T00:00:00', 1)")
        conn.execute("INSERT INTO patients (id, label, notes, created_at, is_builtin) VALUES ('P-017', NULL, NULL, '2026-01-01T00:00:00', 0)")
        conn.execute("INSERT INTO sessions (patient_id, schema_version, source, source_ref, status, start_time, end_time, total_reps) "
                     "VALUES ('P-017', 2, 'video', 'clip.mp4', 'completed', '2026-01-01T10:00:00', '2026-01-01T10:05:00', 3)")
        conn.execute("INSERT INTO reviews (session_id, reviewed_at, notes, next_step) VALUES (1, '2026-01-02T10:00:00', 'ok', 'continue')")
        conn.execute("INSERT INTO goals (patient_id, exercise_name, target_rom, target_reps, set_at) VALUES ('P-017', 'Knee Extension', 120, 10, '2026-01-02T10:00:00')")
        conn.commit(); conn.close()
        with SessionStore(tmp_db).open() as store:
            versions = [r[0] for r in store.conn.execute("SELECT version FROM schema_version ORDER BY version")]
            tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert store.get_review(1).next_step == "continue" and store.get_goal("P-017", "Knee Extension").target_rom == 120.0
            assert [tuple(r) for r in store.conn.execute("SELECT adherence_threshold FROM tracker_settings")] == [(60,)]
        assert versions == [v for v, _ in MIGRATIONS] and {"assignments", "discharges", "tracker_settings"} <= tables


class TestModels:
    def test_enums_definitions_exceptions(self):
        assert models.ASSIGNMENT_STATUSES == ("scheduled", "active", "completed", "superseded")
        assert models.QUEUE_KINDS == ("pending_review", "attention_flag", "practice_gap", "low_adherence")
        assert METRIC_DEFINITIONS["adherence_pct"]["unit"] == "percent" and METRIC_DEFINITIONS["sessions_per_week"]["unit"] == "count"
        assert issubclass(ProgramValidationError, PTLogError) and issubclass(AssignmentValidationError, PTLogError)
        import dataclasses
        for name, fields in {
            "Program": {"id", "name", "description", "exercise_keys", "exercise_names"},
            "Assignment": {"id", "patient_id", "program_id", "program_name", "exercise_keys", "sessions_per_week", "start_date", "end_date", "created_at"},
            "Discharge": {"patient_id", "discharged_on", "reason", "created_at"},
            "AdherenceWeek": {"index", "start", "end", "planned", "recorded", "counted", "exercises_performed", "exercises_missing", "missed", "in_progress"},
            "Adherence": {"assignment", "status", "weeks", "percentage", "note"},
            "RosterRow": {"patient_id", "label", "is_builtin", "program_id", "program_name", "program_status", "days_since_last",
                          "sessions_7d", "sessions_30d", "adherence_pct", "adherence_note", "pending_reviews", "open_flags",
                          "practice_gap", "last_next_step", "needs_attention"},
            "QueueItem": {"kind", "patient_id", "target", "session_id", "age_days", "description"},
            "QueueResult": {"items", "totals"},
            "TrackerSettings": {"adherence_threshold"},
        }.items():
            assert fields <= {f.name for f in dataclasses.fields(getattr(models, name))}, name


# ======================================================================================
# T005 — store primitives
# ======================================================================================

class TestStorePrimitives:
    def test_assign_supersede_history_active(self, fixed_store):
        store, clock = fixed_store
        store.add_patient("P-017")
        a1 = store.assign_program("P-017", "knee_rehab", "Knee Rehabilitation", KEYS, 3, date(2026, 3, 1))
        assert a1.exercise_keys == KEYS and a1.created_at == "2026-03-23T09:15:00" and a1.end_date is None
        a2 = store.assign_program("P-017", "custom", "Custom", ["squat"], 2, date(2026, 3, 15))
        history = store.assignment_history("P-017")
        assert [h.id for h in history] == [a2.id, a1.id] and history[1].end_date == "2026-03-14"
        assert store.active_assignment("P-017", on=date(2026, 3, 20)).id == a2.id
        assert store.active_assignment("P-017", on=date(2026, 3, 10)).id == a1.id
        assert store.active_assignment("P-017", on=date(2026, 2, 1)) is None

    @pytest.mark.parametrize("kwargs,exc,rule", [
        ({"sessions_per_week": 0}, AssignmentValidationError, "1–14"),
        ({"sessions_per_week": 15}, AssignmentValidationError, "1–14"),
        ({"end_date": date(2026, 2, 1)}, AssignmentValidationError, "end date"),
        ({"exercise_keys": []}, ProgramValidationError, "at least one"),
        ({"exercise_keys": ["knee_extension", "bogus"]}, ProgramValidationError, "bogus"),
    ])
    def test_assign_validation(self, fixed_store, kwargs, exc, rule):
        store, _ = fixed_store
        store.add_patient("P-017")
        params = dict(program_id="custom", program_name="Custom", exercise_keys=["knee_extension"], sessions_per_week=3, start_date=date(2026, 3, 1))
        params.update(kwargs)
        with pytest.raises(exc) as e:
            store.assign_program("P-017", **params)
        assert rule in str(e.value)

    def test_assign_refusals(self, fixed_store):
        store, _ = fixed_store
        with pytest.raises(BuiltinPatientError):
            store.assign_program("unassigned", "custom", "Custom", ["squat"], 3, date(2026, 3, 1))
        with pytest.raises(PatientNotFoundError):
            store.assign_program("ghost", "custom", "Custom", ["squat"], 3, date(2026, 3, 1))

    def test_discharge_reactivate_lists(self, fixed_store):
        store, clock = fixed_store
        store.add_patient("P-017"); store.add_patient("P-018")
        d = store.discharge("P-017", date(2026, 3, 20), "goals met")
        assert (d.patient_id, d.discharged_on, d.reason) == ("P-017", "2026-03-20", "goals met")
        assert [p.id for p in store.active_patients()] == ["unassigned", "P-018"]
        assert [(p.id, x.reason) for p, x in store.discharged_patients()] == [("P-017", "goals met")]
        with pytest.raises(PTLogError) as exc:
            store.discharge("P-018", date(2026, 3, 20), "seen by Jane Doe")
        assert "name" in str(exc.value)
        with pytest.raises(BuiltinPatientError):
            store.discharge("unassigned", date(2026, 3, 20))
        assert store.reactivate("P-017") is True and store.reactivate("P-017") is False
        assert store.get_discharge("P-017") is None and [p.id for p in store.active_patients()] == ["unassigned", "P-017", "P-018"]

    def test_threshold_and_latest_review(self, fixed_store, make_session):
        store, clock = fixed_store
        assert store.get_adherence_threshold() == 60
        assert store.set_adherence_threshold(30) == 30 and store.get_adherence_threshold() == 30
        for bad in (0, 101):
            with pytest.raises(PTLogError):
                store.set_adherence_threshold(bad)
        store.add_patient("P-017")
        assert store.latest_review("P-017") is None
        older = make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=5), [(90, 78.0, 3.0)])
        newer = make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=1), [(90, 78.0, 3.0)])
        store.set_review(newer, "hold"); store.set_review(older, "progress")
        assert store.latest_review("P-017").next_step == "hold"

    def test_delete_patient_removes_tracker_rows(self, fixed_store):
        store, _ = fixed_store
        store.add_patient("P-017")
        store.assign_program("P-017", "custom", "Custom", ["squat"], 3, date(2026, 3, 1))
        store.discharge("P-017", date(2026, 3, 20))
        store.delete_patient("P-017")
        for table in ("assignments", "discharges"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


# ======================================================================================
# T011 — roster (User Story 1)
# ======================================================================================

from src.ptlog import adherence, tracker  # noqa: E402

KE = [(90, 78.0, 3.0)]


def seed_roster(store, clock, caseload):
    """A: declining form, one pending; B: quiet 20 days; C: discharged; D: no sessions; unassigned: one reviewed."""
    t = {"target_reps": 1}
    ids = caseload(store, clock, {
        "P-017": [(18, "Knee Extension", [(90, 78.0, 3.0)], t), (12, "Knee Extension", [(86, 78.0, 3.0)], t),
                  (5, "Knee Extension", [(81, 78.0, 3.0)], t), (2, "Knee Extension", [(75, 78.0, 3.0)], t)],
        "P-018": [(20, "Knee Extension", KE, t)],
        "P-019": [(3, "Squat", [(88, 90.0, 2.5)], t)],
        "P-020": [],
        "unassigned": [(2, "Squat", [(88, 90.0, 2.5)], t)],
    })
    for sid, step in zip(ids["P-017"][:3], ("continue", "continue", "hold")):
        store.set_review(sid, step)
    store.set_review(ids["P-018"][0], "continue")
    store.set_review(ids["unassigned"][0], "continue")
    store.discharge("P-019", TODAY, "goals met")
    return ids


class TestRoster:
    def test_columns(self, fixed_store, caseload):
        store, clock = fixed_store
        seed_roster(store, clock, caseload)
        rows = {r.patient_id: r for r in tracker.roster(store, now=D0)}
        assert set(rows) == {"unassigned", "P-017", "P-018", "P-020"}
        a = rows["P-017"]
        assert (a.sessions_7d, a.sessions_30d, a.pending_reviews, a.open_flags, a.last_next_step, a.days_since_last) == (2, 4, 1, 1, "hold", 2)
        assert (a.program_name, a.program_status, a.adherence_pct, a.adherence_note, a.practice_gap, a.needs_attention) == ("none", "none", None, "no program", False, True)
        b = rows["P-018"]
        assert (b.days_since_last, b.practice_gap, b.pending_reviews, b.open_flags, b.needs_attention, b.last_next_step) == (20, True, 0, 0, True, "continue")
        d = rows["P-020"]
        assert (d.days_since_last, d.sessions_7d, d.sessions_30d, d.pending_reviews, d.open_flags, d.needs_attention) == (None, 0, 0, 0, 0, False)
        assert rows["unassigned"].is_builtin is True and rows["unassigned"].program_name == "none"

    def test_attention_and_id_sort(self, fixed_store, caseload):
        store, clock = fixed_store
        seed_roster(store, clock, caseload)
        assert [r.patient_id for r in tracker.roster(store, now=D0)] == ["P-017", "P-018", "unassigned", "P-020"]
        assert [r.patient_id for r in tracker.roster(store, now=D0, sort="id")] == ["unassigned", "P-017", "P-018", "P-020"]

    def test_adherence_column_and_program_filter(self, fixed_store, caseload):
        store, clock = fixed_store
        seed_roster(store, clock, caseload)
        store.assign_program("P-017", "knee_rehab", "Knee Rehabilitation", KEYS, 3, TODAY - timedelta(days=21))
        rows = {r.patient_id: r for r in tracker.roster(store, now=D0)}
        a = rows["P-017"]
        expected = adherence.compute(store.active_assignment("P-017", TODAY),
                                     store.sessions_in_period("P-017", None), TODAY).percentage
        assert a.adherence_pct == expected == 44 and a.program_name == "Knee Rehabilitation" and a.program_status == "active"
        assert [r.patient_id for r in tracker.roster(store, now=D0, program="knee_rehab")] == ["P-017"]
        assert [r.patient_id for r in tracker.roster(store, now=D0, needs_attention=True)] == ["P-017", "P-018"]

    def test_builtin_without_sessions_is_hidden(self, fixed_store, caseload):
        store, clock = fixed_store
        caseload(store, clock, {"P-017": [(2, "Knee Extension", KE)]})
        assert [r.patient_id for r in tracker.roster(store, now=D0)] == ["P-017"]

    def test_snapshot_loads_sessions_once_per_patient(self, tmp_db, caseload):
        from tests.fixtures.golden.sequence import FixedClock

        class CountingStore(SessionStore):
            calls = 0

            def sessions_in_period(self, patient_id, since):
                CountingStore.calls += 1
                return super().sessions_in_period(patient_id, since)

        clock = FixedClock(D0)
        with CountingStore(tmp_db, clock=clock).open() as store:
            seed_roster(store, clock, caseload)
            CountingStore.calls = 0
            rows = tracker.roster(store, now=D0)
        assert CountingStore.calls <= len(rows)


# ======================================================================================
# T023 — adherence view (User Story 3)
# ======================================================================================

from src.ptlog import views  # noqa: E402


class TestAdherenceView:
    def test_adherence_for_and_lines(self, fixed_store, caseload):
        store, clock = fixed_store
        store.add_patient("P-017")
        t = {"target_reps": 1}
        # assignment start 2026-03-01; sessions: week1 x3, week2 x1, week3 x0, week4 (current) x2; today 2026-03-23
        caseload(store, clock, {"P-017": [(22, "Knee Extension", KE, t), (20, "Partial Squat", [(85, 40.0, 2.0)], t),
                                          (18, "Knee Extension", KE, t), (14, "Knee Extension", KE, t),
                                          (1, "Knee Extension", KE, t), (0, "Knee Extension", KE, t)]})
        store.assign_program("P-017", "custom", "Custom", ["knee_extension", "partial_squat"], 3, date(2026, 3, 1))
        adh = tracker.adherence_for(store, "P-017", TODAY)
        assert adh.percentage == 44 and [w.recorded for w in adh.weeks] == [3, 1, 0, 2]
        lines = views.adherence_lines(adh)
        assert lines[0].startswith("Custom — 3 sessions/week from 2026-03-01 (active)")
        assert "week 3  2026-03-15..2026-03-21  0/3  missed | performed: — | missing: knee_extension, partial_squat" in lines
        assert any(l.startswith("week 4  2026-03-22..2026-03-28  2/3  in progress") for l in lines)
        assert lines[-1] == "Adherence: 44% over 3 complete weeks"
        rows = views.adherence_table_rows(adh)
        assert rows[0]["week"] == 1 and rows[0]["recorded"] == "3/3" and rows[2]["status"] == "missed"

    def test_no_program_and_first_week(self, fixed_store, caseload):
        store, clock = fixed_store
        store.add_patient("P-017")
        assert views.adherence_lines(tracker.adherence_for(store, "P-017", TODAY)) == ["No program assigned."]
        store.assign_program("P-017", "custom", "Custom", ["knee_extension"], 3, TODAY - timedelta(days=2))
        lines = views.adherence_lines(tracker.adherence_for(store, "P-017", TODAY))
        assert lines[-1] == "First week in progress; adherence is computed after the first complete week."
        with pytest.raises(PatientNotFoundError):
            tracker.adherence_for(store, "ghost", TODAY)


# ======================================================================================
# T029 — queue (User Story 4)
# ======================================================================================

import time  # noqa: E402


def seed_queue(store, clock, caseload):
    t = {"target_reps": 1}
    ids = caseload(store, clock, {
        "P-017": [(18, "Knee Extension", [(90, 78.0, 3.0)], t), (12, "Knee Extension", [(86, 78.0, 3.0)], t),
                  (5, "Knee Extension", [(81, 78.0, 3.0)], t), (2, "Knee Extension", [(75, 78.0, 3.0)], t)],
        "P-018": [(9, "Knee Extension", KE, t)],
        "P-019": [(20, "Squat", [(88, 90.0, 2.5)], t), (19, "Squat", [(88, 90.0, 2.5)], t), (13, "Squat", [(88, 90.0, 2.5)], t),
                  (12, "Squat", [(88, 90.0, 2.5)], t), (6, "Squat", [(88, 90.0, 2.5)], t), (5, "Squat", [(88, 90.0, 2.5)], t)],
    })
    for sid in ids["P-017"][:2]:
        store.set_review(sid, "continue")
    for sid in ids["P-019"]:
        store.set_review(sid, "continue")
    store.assign_program("P-019", "custom", "Custom", ["squat"], 5, TODAY - timedelta(days=21))
    return ids


class TestQueue:
    def test_kinds_order_and_targets(self, fixed_store, caseload):
        store, clock = fixed_store
        ids = seed_queue(store, clock, caseload)
        q = tracker.queue(store, now=D0)
        pending = q.items["pending_review"]
        assert [(i.patient_id, i.session_id, i.age_days) for i in pending] == [("P-018", ids["P-018"][0], 9), ("P-017", ids["P-017"][2], 5), ("P-017", ids["P-017"][3], 2)]
        assert pending[0].target == f"session:{ids['P-018'][0]}"
        flags = q.items["attention_flag"]
        assert len(flags) == 1 and flags[0].patient_id == "P-017" and "form_declining" in flags[0].description and flags[0].target == "flags:P-017"
        gaps = q.items["practice_gap"]
        assert [(g.patient_id, g.age_days) for g in gaps] == [("P-018", 9)]
        low = q.items["low_adherence"]
        assert len(low) == 1 and low[0].patient_id == "P-019" and "40%" in low[0].description and "60%" in low[0].description and low[0].target == "adherence:P-019"
        assert q.totals == {"pending_review": 3, "attention_flag": 1, "practice_gap": 1, "low_adherence": 1} and q.count == 6

    def test_items_resolve(self, fixed_store, caseload):
        store, clock = fixed_store
        ids = seed_queue(store, clock, caseload)
        store.set_adherence_threshold(30)
        assert tracker.queue(store, now=D0).items["low_adherence"] == []
        store.set_review(ids["P-018"][0], "hold")
        q = tracker.queue(store, now=D0)
        assert q.totals["pending_review"] == 2 and all(i.patient_id == "P-017" for i in q.items["pending_review"])
        store.discharge("P-017", TODAY)
        q = tracker.queue(store, now=D0)
        assert all(i.patient_id != "P-017" for kind in q.items.values() for i in kind)

    def test_empty_caseload(self, fixed_store):
        store, _ = fixed_store
        q = tracker.queue(store, now=D0)
        assert q.count == 0 and all(v == [] for v in q.items.values())

    def test_performance_50_patients(self, fixed_store, make_session):
        store, clock = fixed_store
        store.conn.execute("PRAGMA synchronous=OFF")
        for p in range(50):
            pid = f"P-{p:03d}"
            store.add_patient(pid)
            for i in range(20):
                make_session(store, clock, pid, "Knee Extension", D0 - timedelta(days=60 - i * 3), [(85 + i % 10, 78.0, 3.0)])
            if p % 2 == 0:
                store.assign_program(pid, "custom", "Custom", ["knee_extension"], 3, TODAY - timedelta(days=28))
        t0 = time.perf_counter(); rows = tracker.roster(store, now=D0); t_roster = time.perf_counter() - t0
        t0 = time.perf_counter(); q = tracker.queue(store, now=D0); t_queue = time.perf_counter() - t0
        assert len(rows) == 50 and q.count > 0
        assert t_roster < 3.0 and t_queue < 3.0, (t_roster, t_queue)


class TestPerPatientThresholds:
    """Feature 005 US2: roster and queue use each patient's effective adherence and gap thresholds."""

    def _low(self, store):
        return [i.patient_id for i in tracker.queue(store, now=D0).items["low_adherence"]]

    def _needs(self, store):
        return {r.patient_id: r.needs_attention for r in tracker.roster(store, now=D0)}

    def test_adherence_override_and_reset(self, fixed_store, caseload):
        store, clock = fixed_store
        seed_queue(store, clock, caseload)
        pct = {r.patient_id: r.adherence_pct for r in tracker.roster(store, now=D0)}["P-019"]
        assert pct is not None and pct < 60
        assert self._low(store) == ["P-019"] and self._needs(store)["P-019"] is True
        store.set_patient_threshold("P-019", "adherence", pct)          # "below the threshold" is strict
        assert self._low(store) == [] and self._needs(store)["P-019"] is False
        store.reset_patient_threshold("P-019", "adherence")
        store.set_installation_threshold("adherence", pct)
        assert self._low(store) == []
        store.set_patient_threshold("P-019", "adherence", 90)
        (item,) = tracker.queue(store, now=D0).items["low_adherence"]
        assert "below the 90% threshold" in item.description

    def test_gap_threshold_per_patient(self, fixed_store, caseload):
        store, clock = fixed_store
        seed_queue(store, clock, caseload)
        gaps = lambda: [i.patient_id for i in tracker.queue(store, now=D0).items["practice_gap"]]  # noqa: E731
        assert "P-018" in gaps()                                          # 9 days since the last session
        store.set_patient_threshold("P-018", "practice_gap", 14)
        assert "P-018" not in gaps()

    def test_roster_loads_thresholds_once(self, fixed_store, caseload, monkeypatch):
        store, clock = fixed_store
        seed_queue(store, clock, caseload)
        calls = {"one": 0, "all": 0}
        real_one, real_all = store.effective_thresholds, store.effective_thresholds_all
        monkeypatch.setattr(store, "effective_thresholds", lambda pid: calls.__setitem__("one", calls["one"] + 1) or real_one(pid))
        monkeypatch.setattr(store, "effective_thresholds_all", lambda: calls.__setitem__("all", calls["all"] + 1) or real_all())
        tracker.roster(store, now=D0)
        tracker.queue(store, now=D0)
        assert calls == {"one": 0, "all": 2}
