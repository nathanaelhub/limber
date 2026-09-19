"""T004 — program and exercise catalog from the configuration (FR-005)."""

from pathlib import Path

import pytest

from src.ptlog import importer, programs
from src.ptlog.models import ProgramValidationError

SMALL = Path(__file__).resolve().parent / "fixtures" / "config_small.yaml"


class TestCatalog:
    def test_small_config(self):
        cat = programs.load_catalog(SMALL)
        assert set(cat.exercises) == {"knee_extension", "partial_squat"}
        assert cat.exercises["partial_squat"]["display_name"] == "Partial Squat"
        p = cat.programs["mini_knee"]
        assert (p.id, p.name, p.exercise_keys) == ("mini_knee", "Mini Knee", ["knee_extension", "partial_squat"])
        assert p.exercise_names == ["Knee Extension", "Partial Squat"] and p.description == ""

    def test_real_config_programs(self):
        ps = programs.list_programs()
        assert [p.id for p in ps] == ["knee_rehab", "shoulder_mobility", "hip_strengthening", "general_conditioning"]
        knee = programs.get_program("knee_rehab")
        assert knee.name == "Knee Rehabilitation" and len(knee.exercise_keys) == 5
        assert knee.exercise_keys[0] == "knee_extension" and knee.exercise_names[1] == "Knee Extension (Right)"
        assert programs.get_program("nope") is None

    def test_exercise_name_fallback(self):
        assert programs.exercise_name("knee_extension_right") == "Knee Extension (Right)"
        assert programs.exercise_name("removed_exercise") == "removed_exercise"

    def test_validate_keys(self):
        assert programs.validate_exercise_keys(["knee_extension", "squat"]) == ["knee_extension", "squat"]
        with pytest.raises(ProgramValidationError) as exc:
            programs.validate_exercise_keys(["knee_extension", "bogus", "also_bogus"])
        assert "bogus" in str(exc.value) and "also_bogus" in str(exc.value)
        with pytest.raises(ProgramValidationError) as exc:
            programs.validate_exercise_keys([])
        assert "at least one" in str(exc.value)

    def test_custom_program(self):
        p = programs.custom_program(["squat"])
        assert (p.id, p.name, p.exercise_keys, p.exercise_names) == ("custom", "Custom", ["squat"], ["Squat"])

    def test_importer_delegates(self):
        legacy = importer.exercise_catalog()
        cat = programs.load_catalog()
        assert legacy["knee extension (right)"]["key"] == "knee_extension_right"
        assert set(legacy) == {v["display_name"].lower() for v in cat.exercises.values()}
