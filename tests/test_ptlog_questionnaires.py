"""Feature 013 T004 — scoring a questionnaire, and when the next one is due.

Reversal and missing items are where scoring engines go quietly wrong, so every case here carries its
arithmetic in a comment. The stored snapshot must reproduce a total years later, with the definition
edited or gone.
"""

from datetime import date

import pytest

from src.ptlog import instruments, questionnaires as q
from src.ptlog.models import EntryValidationError

DEF = """
key: demo
name: Demo Four
meaning: What the patient can do day to day, from their own answers.
unit: points (0-12)
direction: higher_is_better
version: 3
scoring: sum
missing:
  minimum_answered: 3
  replace_with_mean: true
choices:
  - {text: Not at all, value: 0}
  - {text: A little, value: 1}
  - {text: Mostly, value: 2}
  - {text: Easily, value: 3}
items:
  - {key: a, text: Walking}
  - {key: b, text: Stairs}
  - {key: c, text: Kneeling}
  - {key: d, text: How much it hurts, reversed: true}
subscales:
  - {key: doing, name: Doing things, items: [a, b, c]}
  - {key: hurt, name: Pain, items: [d]}
"""


def make(folder, text=DEF, name="demo.yaml"):
    (folder / name).write_text(text)
    loaded = instruments.load(folder, reload=True)
    assert loaded.problems == [], loaded.problems
    return loaded.by_key["demo"]


@pytest.fixture
def demo(tmp_path):
    return make(tmp_path)


class TestScoring:
    def test_sum_with_one_reversed_item(self, demo):
        # a 3 + b 2 + c 1 = 6, and d 0 reversed within 0-3 becomes 3 → 9 of 12
        s = q.score(demo, {"a": 3, "b": 2, "c": 1, "d": 0})
        assert s.total == 9 and s.answered == 4 and s.missing == 0
        assert s.subscales == {"doing": 6, "hurt": 3}
        assert (s.minimum, s.maximum) == (0, 12)

    def test_the_reversal_is_within_the_items_own_range(self, tmp_path):
        # d's own choices run 0-10, so 8 reversed is 2, not 3 - 8
        text = DEF.replace("  - {key: d, text: How much it hurts, reversed: true}",
                           "  - key: d\n    text: How much it hurts\n    reversed: true\n    choices:\n"
                           "      - {text: None, value: 0}\n      - {text: Some, value: 8}\n"
                           "      - {text: A lot, value: 10}")
        demo = make(tmp_path, text.replace("unit: points (0-12)", "unit: points (0-19)"))
        assert q.score(demo, {"a": 3, "b": 3, "c": 3, "d": 8}).total == 11      # 9 + (0 + 10 - 8)
        assert q.score(demo, {"a": 0, "b": 0, "c": 0, "d": 0}).total == 10      # 0 + (10 - 0)

    def test_mean_scoring(self, tmp_path):
        demo = make(tmp_path, DEF.replace("scoring: sum", "scoring: mean"))
        # (3 + 2 + 1 + reversed 0 → 3) / 4 = 2.25
        assert q.score(demo, {"a": 3, "b": 2, "c": 1, "d": 0}).total == pytest.approx(2.25, abs=0.06)
        assert q.score(demo, {"a": 3, "b": 3, "c": 3, "d": 0}).total == 3.0

    def test_a_missing_item_is_replaced_by_the_mean_of_the_answered(self, demo):
        # answered a 3, b 2, d reversed 3 → mean 2.67, standing in for c → 3 + 2 + 2.7 + 3 = 10.7
        s = q.score(demo, {"a": 3, "b": 2, "d": 0})
        assert s.answered == 3 and s.missing == 1
        assert s.total == pytest.approx(10.7, abs=0.05)
        assert s.subscales["doing"] == pytest.approx(7.5, abs=0.05)   # a 3 + b 2 + mean of its own two (2.5)
        assert s.subscales["hurt"] == 3

    def test_without_the_replacement_rule_a_missing_item_simply_does_not_count(self, tmp_path):
        demo = make(tmp_path, DEF.replace("  replace_with_mean: true", "  replace_with_mean: false"))
        s = q.score(demo, {"a": 3, "b": 2, "d": 0})
        assert s.total == 8 and s.missing == 1                        # 3 + 2 + reversed 3

    def test_too_few_answers_are_refused_rather_than_scored(self, demo):
        with pytest.raises(EntryValidationError) as err:
            q.score(demo, {"a": 3, "b": 2})
        assert "3" in str(err.value)

    @pytest.mark.parametrize("answers", [
        {"a": 3, "b": 2, "c": 1, "d": 4},              # not one of the choices
        {"a": 3, "b": 2, "c": 1, "d": -1},
        {"a": 3, "b": 2, "c": 1, "e": 0},              # not an item of this instrument
        {"a": 3, "b": 2, "c": 1, "d": "0"},            # not a number
        {"a": 3, "b": 2, "c": 1, "d": True},
        {"a": 3, "b": 2, "c": 1, "d": 1.5},
        [],
        None,
    ])
    def test_refusals(self, demo, answers):
        with pytest.raises(EntryValidationError):
            q.score(demo, answers)

    def test_a_subscale_with_nothing_answered_has_no_score(self, tmp_path):
        demo = make(tmp_path, DEF.replace("  minimum_answered: 3", "  minimum_answered: 2"))
        s = q.score(demo, {"a": 3, "b": 3})
        assert s.subscales["hurt"] is None and s.subscales["doing"] == pytest.approx(9.0, abs=0.05)


class TestSnapshot:
    def test_a_stored_score_can_be_reproduced_without_the_definition(self, demo, tmp_path):
        answers = {"a": 3, "b": 2, "c": 1, "d": 0}
        snap = q.snapshot(demo, answers)
        assert snap["instrument"] == "demo" and snap["version"] == 3 and snap["scoring"] == "sum"
        assert snap["unit"] == "points (0-12)" and snap["direction"] == "higher_is_better"
        (tmp_path / "demo.yaml").unlink()                              # the definition is gone
        instruments.load(tmp_path, reload=True)
        again = q.rescore(snap)
        assert again.total == 9 and again.subscales == {"doing": 6, "hurt": 3}

    def test_editing_the_definition_does_not_change_a_stored_score(self, tmp_path):
        demo = make(tmp_path)
        snap = q.snapshot(demo, {"a": 3, "b": 2, "c": 1, "d": 0})
        edited = make(tmp_path, DEF.replace("  - {key: d, text: How much it hurts, reversed: true}",
                                            "  - {key: d, text: How much it hurts}").replace("version: 3", "version: 4"))
        assert q.score(edited, {"a": 3, "b": 2, "c": 1, "d": 0}).total == 6      # no longer reversed
        assert q.rescore(snap).total == 9                                        # what was answered stands
        assert q.differs_from_installed(snap, edited) is True
        assert q.differs_from_installed(snap, demo) is False


class TestDue:
    START = date(2026, 9, 1)

    @pytest.mark.parametrize("interval, last, expected", [
        ("once", None, date(2026, 9, 1)),
        ("once", date(2026, 9, 10), None),
        ("weekly", None, date(2026, 9, 1)),
        ("weekly", date(2026, 9, 10), date(2026, 9, 17)),
        ("fortnightly", date(2026, 9, 10), date(2026, 9, 24)),
        ("monthly", date(2026, 9, 10), date(2026, 10, 10)),
        ("monthly", date(2026, 1, 31), date(2026, 2, 28)),           # clamped to the end of the month
    ])
    def test_next_due(self, interval, last, expected):
        assert q.next_due(interval, self.START, last) == expected

    def test_due_today_and_overdue(self):
        assert q.is_due(date(2026, 9, 24), date(2026, 9, 24)) is True
        assert q.is_due(date(2026, 9, 25), date(2026, 9, 24)) is False
        assert q.is_due(None, date(2026, 9, 24)) is False
        assert q.is_overdue(date(2026, 9, 24), date(2026, 10, 2)) is True     # more than seven days past
        assert q.is_overdue(date(2026, 9, 24), date(2026, 10, 1)) is False    # exactly seven: not yet
        assert q.is_overdue(date(2026, 9, 24), date(2026, 9, 30)) is False
        assert q.is_overdue(None, date(2026, 10, 1)) is False

    def test_the_intervals_are_named_and_described(self):
        assert [k for k, _ in q.INTERVALS] == ["once", "weekly", "fortnightly", "monthly"]
        assert all(len(words) > 4 for _, words in q.INTERVALS)
        with pytest.raises(EntryValidationError):
            q.next_due("whenever", self.START, None)
