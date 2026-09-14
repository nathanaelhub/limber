"""T036 — every legacy format is reproduced byte for byte from the canonical record (FR-022, SC-005)."""

import json
from pathlib import Path

import pytest

from analyze import ExerciseConfig
from src.form_assessment import FeedbackPriority
from src.ptlog import exports
from src.ptlog.exports.csv_report import to_csv_report
from src.ptlog.exports.observation_json import to_observation_dict, to_observation_json
from src.ptlog.exports.pta_log import to_pta_log_text
from src.ptlog.exports.text_log import to_text_log
from src.ptlog.recorder import SessionRecorder
from src.ptlog.store import SessionStore
from src.session_summary import generate_session_summary
from tests.fixtures.golden.sequence import (
    CAMERA_ID, FRAME_SKIP, IMGSZ, PATIENT_ID, SEQUENCE, SETS, SOURCE, START, FixedClock, ts_for,
)
from tests.test_ptlog_recorder import FakeTracker, assessment, metrics_for

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"


def cfg(key):
    s = SETS[key]
    return ExerciseConfig(name=s["exercise_name"], keypoints=[11, 13, 15], up_angle=s["up_angle"],
                          down_angle=s["down_angle"], form_tolerance=15, target_reps=s["target_reps"], side=s["side"])


def replay(store, clock, end=True):
    """Drive SEQUENCE through the recorder exactly as the engine loops would."""
    store.add_patient(PATIENT_ID)
    rec = SessionRecorder(store, clock=clock)
    key = "knee_extension"
    tracker = FakeTracker(cfg(key))
    clock.set(START)
    sid = rec.start(PATIENT_ID, SOURCE, str(CAMERA_ID), cfg(key), exercise_key=key,
                    extras={"camera_id": CAMERA_ID, "imgsz": IMGSZ, "frame_skip": FRAME_SKIP})
    for kind, p in SEQUENCE:
        clock.set(ts_for(p["frame_num"]))
        f = p["frame_num"]
        if kind == "sample":
            tracker.current_state = p["state"]
            rec.observe(tracker, metrics_for(tracker, p["angle"]), p["angle"], f, None)
        elif kind == "rep":
            tracker.complete_rep(min_angle=p["min_angle"], max_angle=p["max_angle"], rom=p["rom"],
                                 duration=p["duration_seconds"], form=p["form_score"])
            rec.observe(tracker, metrics_for(tracker, None), None, f, None)
        elif kind == "partial":
            tracker.partial(p["reason"], rom=p["rom"])
            tracker.session.partial_rep_metrics[-1].min_angle = p["min_angle"]
            tracker.session.partial_rep_metrics[-1].max_angle = p["max_angle"]
            tracker.session.partial_rep_metrics[-1].duration_seconds = p["duration_seconds"]
            rec.observe(tracker, metrics_for(tracker, None), None, f, None)
        elif kind == "form":
            rec.observe(tracker, metrics_for(tracker, None), None, f,
                        assessment(p["status"], getattr(FeedbackPriority, p["priority"]), p["message"], p["body_part"]))
        elif kind == "switch":
            ip = p["interrupted_partial"]
            tracker.partial("interrupted", rom=ip["rom"])
            pr = tracker.session.partial_rep_metrics[-1]
            pr.min_angle, pr.max_angle, pr.duration_seconds = ip["min_angle"], ip["max_angle"], ip["duration_seconds"]
            key = p["to"]
            rec.switch(cfg(key), tracker, f, exercise_key=key)
            tracker = FakeTracker(cfg(key))
        elif kind == "reset":
            rec.reset(tracker, f)
            tracker = FakeTracker(cfg(key))
        elif kind == "end" and end:
            rec.end(tracker.session)
    return sid


@pytest.fixture
def replayed(tmp_db):
    clock = FixedClock()
    with SessionStore(tmp_db, clock=clock).open() as store:
        sid = replay(store, clock)
        yield store, sid


class TestGoldenParity:
    def test_pta_log(self, replayed):
        store, sid = replayed
        assert to_pta_log_text(store.load_session(sid), ordinal=1) == (GOLDEN / "pta_log.txt").read_text()

    def test_observation_json(self, replayed):
        store, sid = replayed
        assert to_observation_json(store.load_session(sid)) == (GOLDEN / "observation.json").read_text()

    def test_csv_report(self, replayed):
        store, sid = replayed
        assert to_csv_report(store.load_session(sid), store.get_patient(PATIENT_ID)) == (GOLDEN / "report.csv").read_bytes().decode("utf-8")

    def test_text_log(self, replayed):
        store, sid = replayed
        assert to_text_log(store.load_session(sid)) == [(GOLDEN / "session.log").read_text()]

    def test_exports_are_deterministic(self, replayed):
        store, sid = replayed
        s = store.load_session(sid)
        assert to_pta_log_text(s, 1) == to_pta_log_text(s, 1)
        assert to_observation_json(s) == to_observation_json(s)

    def test_observation_dict_feeds_session_summary(self, replayed):
        store, sid = replayed
        summary = generate_session_summary(to_observation_dict(store.load_session(sid)))
        assert isinstance(summary, dict) and summary


class TestInterruptedVariants:
    @pytest.fixture
    def interrupted(self, tmp_db):
        clock = FixedClock()
        with SessionStore(tmp_db, clock=clock).open() as store:
            sid = replay(store, clock, end=False)
            store._interrupt_running("recovered_on_open")
            yield store, sid

    def test_pta_has_error_line_before_halt(self, interrupted):
        store, sid = interrupted
        lines = to_pta_log_text(store.load_session(sid), ordinal=1).splitlines()
        assert lines[-1].endswith('| SYSTEM  | "System halted."')
        assert lines[-2].endswith('| ERROR  | "Session interrupted"')
        assert '"Session Summary" | totalReps=6, avgFormScore=91.0, avgRom=80.4' in lines[-3]

    def test_observation_json_marks_interrupted(self, interrupted):
        store, sid = interrupted
        d = to_observation_dict(store.load_session(sid))
        assert d["summary"]["warnings"] == ["Session interrupted"]
        assert d["end_time"] == "2026-03-23T09:15:12.666667"          # last recorded event
        assert d["events"][-1]["type"] == "session_end" and d["events"][-1]["total_reps"] == 6

    def test_csv_flags_interrupted(self, interrupted):
        store, sid = interrupted
        text = to_csv_report(store.load_session(sid), store.get_patient(PATIENT_ID))
        assert "Flags for Review" in text and "Session interrupted" in text

    def test_text_log_marks_interrupted(self, interrupted):
        store, sid = interrupted
        last = to_text_log(store.load_session(sid))[-1].splitlines()[-1]
        assert "SESSION INTERRUPTED | Total Reps: 6 | Avg Form: 91% | Avg ROM: 80.4°" in last


class TestTextLogRollover:
    def test_fifty_line_cap_with_continuation_header(self, tmp_db, fake_clock):
        from src.ptlog.models import ExerciseSetInfo, RepEvent
        with SessionStore(tmp_db, clock=fake_clock).open() as store:
            sid = store.start_session("unassigned", "video", "clip.mp4")
            set_id = store.open_set(sid, ExerciseSetInfo("squat", "Squat", "bilateral", 10, 170.0, 90.0))
            for n in range(1, 61):
                store.add_rep(set_id, RepEvent(n, 88.0, 171.0, 83.0, 2.4, 88.0, f"2026-03-23T09:{16 + n // 60:02d}:{n % 60:02d}", 60 * n))
            store.end_session(sid)
            files = to_text_log(store.load_session(sid))
        assert len(files) == 2
        assert files[0].startswith("# logfile created: 2026-03-23 09:15:00\n")
        assert len(files[0].splitlines()) == 50
        assert files[1].startswith("# continued: ")
        assert files[0].splitlines()[1].endswith("SESSION START | Exercise: Squat | Source: clip.mp4")
        assert files[1].splitlines()[-1].split("] ", 1)[1].startswith("SESSION END | Total Reps: 60")


class TestCsvNotes:
    def test_patient_notes_block(self, tmp_db, fake_clock):
        from src.ptlog.models import ExerciseSetInfo
        with SessionStore(tmp_db, clock=fake_clock).open() as store:
            store.add_patient("P-017", notes="Week 3, cleared for closed-chain work")
            sid = store.start_session("P-017", "video", "clip.mp4")
            store.open_set(sid, ExerciseSetInfo("squat", "Squat", "bilateral", 10, 170.0, 90.0))
            store.end_session(sid)
            text = to_csv_report(store.load_session(sid), store.get_patient("P-017"))
        assert "Therapist Notes\r\n\"Week 3, cleared for closed-chain work\"\r\n" in text or \
               "Therapist Notes\r\nWeek 3, cleared for closed-chain work\r\n" in text


class TestWriteExport:
    def test_names_records_and_registry(self, replayed, tmp_path):
        store, sid = replayed
        assert set(exports.FORMATS) == {"pta_log", "observation_json", "csv_report", "text_log"}
        written = {}
        for fmt in exports.FORMATS:
            paths = exports.write_export(store, sid, fmt, tmp_path)
            assert all(p.exists() for p in paths)
            written[fmt] = paths
        assert written["pta_log"][0].name == "P-001_20260323_091500.txt"
        assert written["observation_json"][0].name == "P-001_20260323_091500.json"
        assert written["csv_report"][0].name == "P-001_20260323_091500.csv"
        assert written["text_log"][0].name == "P-001_20260323_091500_01.log"
        assert written["pta_log"][0].read_text() == (GOLDEN / "pta_log.txt").read_text()
        rows = store.conn.execute("SELECT format, path FROM exports WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
        assert [r[0] for r in rows] == ["pta_log", "observation_json", "csv_report", "text_log"]
        assert all(Path(r[1]).exists() for r in rows)

    def test_unknown_format_and_session(self, replayed, tmp_path):
        from src.ptlog.models import SessionNotFoundError
        store, sid = replayed
        with pytest.raises(ValueError):
            exports.write_export(store, sid, "docx", tmp_path)
        with pytest.raises(SessionNotFoundError):
            exports.write_export(store, 999, "csv_report", tmp_path)
