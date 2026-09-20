"""T039 — roster CSV (FR-018)."""

from datetime import datetime

from src.ptlog import tracker
from src.ptlog.exports import to_roster_csv, write_roster_export
from src.ptlog.models import RosterRow

D0 = datetime(2026, 3, 23, 9, 15, 0)
HEADER = ("patient_id,label,program,program_status,days_since_last_session,sessions_last_7_days,sessions_last_30_days,"
          "adherence_percent,pending_reviews,open_flags,practice_gap,last_next_step")


def rows():
    return [
        RosterRow("P-017", "Post-op knee", False, "knee_rehab", "Knee Rehabilitation", "active", 2, 2, 4, 44, "", 1, 1, True, "hold", True),
        RosterRow("P-020", None, False, None, "none", "none", None, 0, 0, None, "no program", 0, 0, False, None, False),
    ]


class TestRosterCsv:
    def test_header_rows_and_empty_cells(self):
        text = to_roster_csv(rows(), D0)
        lines = text.split("\r\n")
        assert lines[0] == HEADER
        assert lines[1] == "P-017,Post-op knee,Knee Rehabilitation,active,2,2,4,44,1,1,true,hold"
        assert lines[2] == "P-020,,none,none,,0,0,,0,0,false,"
        assert text.endswith("\r\n")

    def test_write_named_by_time_and_includes_all_active(self, fixed_store, caseload, tmp_path):
        store, clock = fixed_store
        caseload(store, clock, {"P-017": [(2, "Knee Extension", [(90, 78.0, 3.0)])], "P-018": [(30, "Squat", [(88, 90.0, 2.5)])]})
        store.discharge("P-018", D0.date())
        path = write_roster_export(store, tmp_path, now=D0)
        assert path.name == "roster_20260323_091500.csv"
        text = path.read_bytes().decode("utf-8")
        assert "P-017" in text and "P-018" not in text
        assert [l.split(",")[0] for l in text.strip().split("\r\n")[1:]] == [r.patient_id for r in tracker.roster(store, now=D0)]
