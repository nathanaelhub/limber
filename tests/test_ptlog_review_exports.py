"""T045 — review summary assembly and the two exports (FR-020 … FR-022)."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.ptlog import review
from src.ptlog.exports import REVIEW_FORMATS, write_review_export
from src.ptlog.exports.review_csv import to_review_csv
from src.ptlog.exports.review_report import to_review_report
from src.ptlog.models import PatientNotFoundError

D0 = datetime(2026, 3, 23, 9, 15, 0)


@pytest.fixture
def patient_history(fixed_store, make_session):
    """Two exercises over three sessions, one goal, one flag (target reps), one reviewed session."""
    store, clock = fixed_store
    store.add_patient("P-017", label="Post-op knee", notes="cleared for closed-chain work")
    store.set_gap_days("P-017", 30)
    ids = [
        make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=20), [(85, 80.0, 2.4)] * 8),
        make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=10), [(86, 84.0, 2.3)] * 8,
                     extra_sets=[{"exercise": "Squat", "reps": [(80, 90.0, 2.5)] * 5}]),
        make_session(store, clock, "P-017", "Knee Extension", D0 - timedelta(days=1), [(88, 88.0, 2.2)] * 8,
                     extra_sets=[{"exercise": "Squat", "reps": [(82, 92.0, 2.5)] * 5}]),
    ]
    clock.set(D0)
    store.set_goal("P-017", "Knee Extension", target_rom=120, target_reps=10)
    store.set_review(ids[1], "progress", "post-op week 3")
    return store, clock, ids


class TestSummary:
    def test_assembly(self, patient_history):
        store, _, ids = patient_history
        s = review.review_summary(store, "P-017", "all", now=D0)
        assert (s.patient_id, s.period, s.period_start, s.generated_at, s.gap_days) == ("P-017", "all", None, D0.isoformat(), 30)
        assert list(s.trends) == ["Knee Extension", "Squat"]
        assert [p.session_id for p in s.trends["Knee Extension"].points] == ids
        assert [f.rule for f in s.flags.flags] == ["target_reps_not_reached"]
        assert s.goals[0]["goal"].target_rom == 120.0 and s.goals[0]["progress_pct"] == 73 and s.goals[0]["latest_reps"] == 8
        assert [x["session"].id for x in s.sessions] == list(reversed(ids))
        assert s.sessions[1]["review"].next_step == "progress" and s.sessions[0]["review"] is None
        assert s.sessions[0]["measures"]["Squat"].reps_completed == 5

    def test_period_start_recorded(self, patient_history):
        store, _, _ = patient_history
        s = review.review_summary(store, "P-017", "14d", now=D0)
        assert s.period_start == (D0 - timedelta(days=14)).isoformat()
        assert len(s.trends["Knee Extension"].points) == 2

    def test_unknown_patient(self, fixed_store):
        store, _ = fixed_store
        with pytest.raises(PatientNotFoundError):
            review.review_summary(store, "ghost", "all", now=D0)


class TestReport:
    def test_sections_and_values(self, patient_history):
        store, _, ids = patient_history
        text = to_review_report(review.review_summary(store, "P-017", "all", now=D0))
        lines = text.splitlines()
        assert lines[:4] == ["PT REVIEW SUMMARY", "Patient: P-017", "Period: all time", "Generated: 2026-03-23 09:15"]
        assert "TRENDS" in lines and "Knee Extension — 3 sessions" in lines and "Squat — 2 sessions" in lines
        row = next(l for l in lines if l.startswith("  2026-03-03"))
        assert all(tok in row for tok in (str(ids[0]), "8/10", "85.0", "80.0", "2.40", "0.00", "0.0", "completed"))
        assert any(l.strip().startswith("change first→latest: reps +0, avg form +3.0, avg ROM +8.0°") for l in lines)
        assert "  goal: ROM 120° (latest 88.0°, 73% of goal), reps 10" in lines
        assert "FLAGS" in lines and any(l.startswith("- [target_reps_not_reached] Knee Extension:") for l in lines)
        assert any(l.startswith("Not evaluated yet:") and "form_declining for Squat" in l for l in lines)
        assert "GOALS" in lines and "Knee Extension: ROM 120° — latest 88.0° (73%); reps 10 — latest 8/10" in lines
        assert "SESSIONS" in lines
        assert f"- 2026-03-22 session {ids[2]} | Knee Extension 8/10, Squat 5/10 | pending review" in lines
        assert (f"- 2026-03-13 session {ids[1]} | Knee Extension 8/10, Squat 5/10 | reviewed 2026-03-23 09:15 | "
                f"next step: progress | notes: post-op week 3") in lines
        assert "Post-op knee" not in text and "cleared for closed-chain" not in text

    def test_period_line_with_dates(self, patient_history):
        store, _, _ = patient_history
        text = to_review_report(review.review_summary(store, "P-017", "30d", now=D0))
        assert "Period: last 30 days (2026-02-21 to 2026-03-23)" in text.splitlines()

    def test_empty_sections_say_so(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-018")
        make_session(store, clock, "P-018", "Squat", D0, [(80, 90.0, 2.5)] * 10)
        store.set_gap_days("P-018", 30)
        text = to_review_report(review.review_summary(store, "P-018", "all", now=D0))
        assert "No flags in this period." in text and "No goals set." in text


class TestCsv:
    HEADER = ("date,session_id,exercise,reps_completed,target_reps,avg_form_score_0_100,avg_rom_degrees,"
              "avg_rep_duration_seconds,tempo_consistency_seconds,partial_rep_share_percent,interrupted,"
              "review_status,next_step,reviewed_at")

    def test_rows(self, patient_history):
        store, _, ids = patient_history
        text = to_review_csv(review.review_summary(store, "P-017", "all", now=D0))
        assert "\r\n" in text
        rows = text.strip().split("\r\n")
        assert rows[0] == self.HEADER and len(rows) == 6
        assert rows[1] == f"2026-03-22,{ids[2]},Knee Extension,8,10,88.0,88.0,2.2,0.0,0.0,false,pending,,"
        assert rows[3] == f"2026-03-13,{ids[1]},Knee Extension,8,10,86.0,84.0,2.3,0.0,0.0,false,reviewed,progress,2026-03-23T09:15:00"
        assert rows[5].startswith(f"2026-03-03,{ids[0]},Knee Extension,8,10,85.0")

    def test_empty_cells_for_missing_values(self, fixed_store, make_session):
        store, clock = fixed_store
        store.add_patient("P-018")
        sid = make_session(store, clock, "P-018", "Squat", D0, [], interrupted=True)
        rows = to_review_csv(review.review_summary(store, "P-018", "all", now=D0)).strip().split("\r\n")
        assert rows[1] == f"2026-03-23,{sid},Squat,0,10,,,,,,true,pending,,"


class TestWriteReviewExport:
    def test_naming_recording_removal_and_determinism(self, patient_history, tmp_path):
        store, _, _ = patient_history
        assert set(REVIEW_FORMATS) == {"review_report", "review_csv"}
        p1 = write_review_export(store, "P-017", "all", "review_report", tmp_path, now=D0)
        p2 = write_review_export(store, "P-017", "all", "review_csv", tmp_path, now=D0)
        assert p1.name == "P-017_review_all_20260323_091500.txt" and p2.name == "P-017_review_all_20260323_091500.csv"
        assert p1.read_text() == to_review_report(review.review_summary(store, "P-017", "all", now=D0))
        rows = store.conn.execute("SELECT format, period, path FROM review_exports ORDER BY id").fetchall()
        assert [(r[0], r[1]) for r in rows] == [("review_report", "all"), ("review_csv", "all")]
        again = write_review_export(store, "P-017", "all", "review_report", tmp_path / "b", now=D0)
        assert again.read_text() == p1.read_text()
        report = store.delete_patient("P-017")
        assert report.export_files == 3 and not p1.exists() and not p2.exists()

    def test_unknown_format(self, patient_history, tmp_path):
        store, _, _ = patient_history
        with pytest.raises(ValueError):
            write_review_export(store, "P-017", "all", "pdf", tmp_path, now=D0)
