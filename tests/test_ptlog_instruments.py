"""Feature 013 T002 — reading questionnaire definitions from YAML files.

A definition file is input, not code: it is parsed safely, checked field by field, and a bad one is
reported by name and skipped without taking the other instruments (or the app) down.
"""

import textwrap

import pytest

from src.ptlog import instruments

GOOD = """
key: demo_knee
name: Demo Knee Function
meaning: How much your knee lets you do day to day, from your own answers.
unit: points (0-8)
direction: higher_is_better
version: 1
notice: Written for this project. Not a validated or licensed instrument.
scoring: sum
missing:
  minimum_answered: 2
  replace_with_mean: true
choices:
  - {text: Not at all, value: 0}
  - {text: A little, value: 1}
  - {text: Easily, value: 2}
items:
  - {key: stairs, text: Going up and down stairs}
  - {key: kneeling, text: Kneeling down}
  - {key: pain_walking, text: Pain when you walk, reversed: true}
subscales:
  - {key: pain, name: Pain, items: [pain_walking]}
  - {key: activity, name: Activity, items: [stairs, kneeling]}
"""


def write(directory, name, text):
    path = directory / name
    path.write_text(textwrap.dedent(text).lstrip())
    return path


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "instruments"
    d.mkdir()
    return d


def test_a_valid_definition_loads_whole(folder):
    write(folder, "demo_knee.yaml", GOOD)
    loaded = instruments.load(folder)
    assert loaded.problems == []
    i = loaded.by_key["demo_knee"]
    assert i.name == "Demo Knee Function" and i.version == 1 and i.scoring == "sum"
    assert i.unit == "points (0-8)" and i.direction == "higher_is_better" and "not a validated" in i.notice.lower()
    assert [x.key for x in i.items] == ["stairs", "kneeling", "pain_walking"]
    assert [(c.text, c.value) for c in i.items[0].choices] == [("Not at all", 0), ("A little", 1), ("Easily", 2)]
    assert i.items[2].reversed is True and i.items[0].reversed is False
    assert i.minimum == 0 and i.maximum == 6                       # three items, 0-2 each
    assert [(s.key, s.item_keys, s.minimum, s.maximum) for s in i.subscales] == [
        ("pain", ["pain_walking"], 0, 2), ("activity", ["stairs", "kneeling"], 0, 4)]
    assert i.minimum_answered == 2 and i.replace_with_mean is True
    assert instruments.load(folder).by_key["demo_knee"] is i        # cached per directory


def test_an_item_may_carry_its_own_choices(folder):
    write(folder, "mixed.yaml", GOOD.replace(
        "  - {key: kneeling, text: Kneeling down}",
        "  - key: kneeling\n    text: Kneeling down\n    choices:\n      - {text: 'No', value: 0}\n      - {text: 'Yes', value: 5}"))
    i = instruments.load(folder).by_key["demo_knee"]
    assert [c.value for c in i.items[1].choices] == [0, 5] and i.maximum == 9


@pytest.mark.parametrize("edit, word", [
    (("scoring: sum", "scoring: median"), "scoring"),
    (("direction: higher_is_better", "direction: sideways"), "direction"),
    (("version: 1", "version: nought"), "version"),
    (("  - {key: kneeling, text: Kneeling down}", "  - {key: stairs, text: Something else}"), "stairs"),
    (("items: [pain_walking]}", "items: [elbow]}"), "elbow"),
    (("meaning: How much your knee lets you do day to day, from your own answers.", "meaning: Score."), "meaning"),
    (("  minimum_answered: 2", "  minimum_answered: 9"), "minimum_answered"),
    (("  - {text: A little, value: 1}", "  - {text: A little, value: nine}"), "value"),
    (("  - {text: A little, value: 1}", "  - {text: A little, value: 0}"), "value"),
])
def test_refusals_name_the_file_and_the_problem(folder, edit, word):
    before, after = edit
    write(folder, "broken.yaml", GOOD.replace(before, after))
    loaded = instruments.load(folder)
    assert loaded.by_key == {}
    assert len(loaded.problems) == 1
    problem = loaded.problems[0]
    assert problem.file == "broken.yaml" and word in problem.message, problem.message


def test_more_refusals(folder):
    for name, text in (
        ("noitems.yaml", GOOD.split("items:")[0] + "items: []\n"),
        ("nokey.yaml", GOOD.replace("key: demo_knee\n", "", 1)),
        ("notamapping.yaml", "- just\n- a list\n"),
        ("notyaml.yaml", "key: [unclosed\n"),
        ("empty.yaml", ""),
    ):
        write(folder, name, text)
    loaded = instruments.load(folder)
    assert loaded.by_key == {} and {p.file for p in loaded.problems} == {
        "noitems.yaml", "nokey.yaml", "notamapping.yaml", "notyaml.yaml", "empty.yaml"}
    assert all(p.message for p in loaded.problems)


def test_an_instrument_may_not_ask_for_identifying_details(folder):
    """The check is by what the item asks for, not by capitalisation: a title like "Demo Knee
    Function" is two capitalised words in a row and must still be allowed."""
    write(folder, "good.yaml", GOOD)
    for name, item in (("a.yaml", "Your full name"), ("b.yaml", "Your date of birth"),
                       ("c.yaml", "Your hospital record number"), ("d.yaml", "Your phone number"),
                       ("e.yaml", "Your email address"), ("f.yaml", "Your home address")):
        write(folder, name, GOOD.replace("key: demo_knee", f"key: k{name[0]}")
              .replace("text: Kneeling down", f"text: {item}"))
    loaded = instruments.load(folder)
    assert list(loaded.by_key) == ["demo_knee"]
    assert len(loaded.problems) == 6 and all("identif" in p.message for p in loaded.problems)


def test_one_bad_file_does_not_stop_the_others(folder):
    write(folder, "demo_knee.yaml", GOOD)
    write(folder, "broken.yaml", GOOD.replace("scoring: sum", "scoring: median").replace("key: demo_knee", "key: other"))
    loaded = instruments.load(folder)
    assert list(loaded.by_key) == ["demo_knee"] and [p.file for p in loaded.problems] == ["broken.yaml"]


def test_two_files_claiming_the_same_key(folder):
    write(folder, "a.yaml", GOOD)
    write(folder, "b.yaml", GOOD)
    loaded = instruments.load(folder)
    assert list(loaded.by_key) == ["demo_knee"] and len(loaded.problems) == 1
    assert "demo_knee" in loaded.problems[0].message and "a.yaml" in loaded.problems[0].message


def test_no_directory_is_not_an_error(tmp_path):
    loaded = instruments.load(tmp_path / "not-there")
    assert loaded.by_key == {} and loaded.problems == []


def test_yaml_is_never_executed(folder):
    """safe_load only: a tag that would construct a Python object must be refused, not run."""
    write(folder, "evil.yaml", "key: evil\nname: !!python/object/apply:os.system ['echo pwned']\n")
    loaded = instruments.load(folder)
    assert loaded.by_key == {} and loaded.problems[0].file == "evil.yaml"


def test_the_shipped_demo_instrument_is_valid_and_says_what_it_is():
    loaded = instruments.load()                                     # the repository's own instruments/
    assert loaded.problems == [], loaded.problems
    demo = loaded.by_key["demo_knee_function"]
    assert len(demo.items) == 10 and demo.scoring == "sum" and demo.maximum == 40
    assert sum(1 for i in demo.items if i.reversed) == 2 and len(demo.subscales) == 2
    assert "not a validated" in demo.notice.lower() and "licensed" in demo.notice.lower()
