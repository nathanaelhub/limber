"""Questionnaire definitions read from YAML files (feature 013).

One file per instrument in `instruments/` beside `config.yaml`, so adding an instrument needs no code.
A definition is input, never code: it is parsed with `yaml.safe_load`, every field is checked, and a
bad file is reported by name and skipped, leaving the other instruments and the app working.

Nothing here scores anything; that is `src/ptlog/questionnaires.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIRECTORY = "instruments"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
SCORING = ("sum", "mean")
DIRECTIONS = ("higher_is_better", "higher_is_worse")
MEANING_MIN = 15

# What an item may not ask for. The free-text privacy check cannot be used here: it treats two
# capitalised words in a row as a name, which would refuse an honest title like "Demo Knee Function".
IDENTIFYING = ("your name", "full name", "first name", "last name", "surname", "date of birth",
               "birth date", "birthday", "record number", "hospital number", "nhs number",
               "insurance number", "phone number", "telephone", "mobile number", "email",
               "address", "postcode", "zip code", "next of kin")


@dataclass(frozen=True)
class Choice:
    text: str
    value: int


@dataclass(frozen=True)
class Item:
    key: str
    text: str
    choices: List[Choice]
    reversed: bool = False

    @property
    def minimum(self) -> int:
        return min(c.value for c in self.choices)

    @property
    def maximum(self) -> int:
        return max(c.value for c in self.choices)

    def values(self) -> List[int]:
        return [c.value for c in self.choices]


@dataclass(frozen=True)
class Subscale:
    key: str
    name: str
    item_keys: List[str]
    minimum: int
    maximum: int


@dataclass(frozen=True)
class Instrument:
    key: str
    name: str
    meaning: str                       # one plain sentence: what the score means
    unit: str
    direction: str                     # higher_is_better | higher_is_worse
    version: int
    scoring: str                       # sum | mean
    items: List[Item]
    subscales: List[Subscale]
    minimum_answered: int
    replace_with_mean: bool
    notice: str = ""
    file: str = ""

    @property
    def minimum(self) -> int:
        return sum(i.minimum for i in self.items) if self.scoring == "sum" else min(i.minimum for i in self.items)

    @property
    def maximum(self) -> int:
        return sum(i.maximum for i in self.items) if self.scoring == "sum" else max(i.maximum for i in self.items)

    def item(self, key: str) -> Optional[Item]:
        return next((i for i in self.items if i.key == key), None)


@dataclass(frozen=True)
class Problem:
    file: str
    message: str


@dataclass
class Instruments:
    by_key: Dict[str, Instrument] = field(default_factory=dict)
    problems: List[Problem] = field(default_factory=list)

    def listed(self) -> List[Instrument]:
        return sorted(self.by_key.values(), key=lambda i: i.name.lower())


class _Bad(Exception):
    """One definition is unusable; the message names what is wrong."""


_CACHE: Dict[str, Instruments] = {}


def default_directory() -> Path:
    return REPO_ROOT / DIRECTORY


def load(directory: Optional[Path] = None, reload: bool = False) -> Instruments:
    """Every instrument in the directory, and a problem for every file that could not be used."""
    path = Path(directory) if directory else default_directory()
    key = str(path)
    if not reload and key in _CACHE:
        return _CACHE[key]
    result = Instruments()
    for file in sorted(path.glob("*.yaml")) if path.is_dir() else []:
        try:
            instrument = _read(file)
        except _Bad as bad:
            result.problems.append(Problem(file.name, str(bad)))
            continue
        if instrument.key in result.by_key:
            result.problems.append(Problem(
                file.name, f"another file ({result.by_key[instrument.key].file}) already defines "
                           f"the instrument '{instrument.key}'"))
            continue
        result.by_key[instrument.key] = instrument
    _CACHE[key] = result
    return result


def forget() -> None:
    """Drop the cache (tests, and the therapist app after a file is added)."""
    _CACHE.clear()


# ----------------------------------------------------------------------------- reading one file


def _read(file: Path) -> Instrument:
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as err:
        raise _Bad(f"the file could not be read as YAML: {err}") from None
    if not isinstance(data, dict):
        raise _Bad("a definition must be a mapping of fields, starting with 'key:'")

    key = _text(data, "key")
    if not KEY_RE.match(key):
        raise _Bad("key must be lower-case letters, digits, and underscores, up to 40 characters")
    name = _text(data, "name")
    meaning = _text(data, "meaning")
    if len(meaning) < MEANING_MIN:
        raise _Bad(f"meaning must be a plain sentence saying what the score means (at least {MEANING_MIN} characters)")
    unit = _text(data, "unit")
    direction = _text(data, "direction")
    if direction not in DIRECTIONS:
        raise _Bad(f"direction must be one of: {', '.join(DIRECTIONS)}")
    scoring = _text(data, "scoring")
    if scoring not in SCORING:
        raise _Bad(f"scoring must be one of: {', '.join(SCORING)}")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _Bad("version must be a whole number of 1 or more")
    notice = str(data.get("notice") or "").strip()

    shared = _choices(data.get("choices"), "choices") if data.get("choices") is not None else None
    items = _items(data.get("items"), shared)
    subscales = _subscales(data.get("subscales"), items)
    minimum_answered, replace_with_mean = _missing(data.get("missing"), len(items))

    return Instrument(key=key, name=name, meaning=meaning, unit=unit, direction=direction, version=version,
                      scoring=scoring, items=items, subscales=subscales, minimum_answered=minimum_answered,
                      replace_with_mean=replace_with_mean, notice=notice, file=file.name)


def _text(data: dict, field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise _Bad(f"{field_name} is required and must be text")
    return value.strip()


def _choices(raw, where: str) -> List[Choice]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise _Bad(f"{where} must be a list of at least two answers")
    choices: List[Choice] = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise _Bad(f"each of {where} must be a mapping with text and value")
        text = entry.get("text")
        value = entry.get("value")
        if not isinstance(text, (str, int)) or str(text).strip() == "":
            raise _Bad(f"each of {where} needs text")
        if not isinstance(value, int) or isinstance(value, bool):
            raise _Bad(f"each of {where} needs a whole-number value (got {value!r})")
        if value in seen:
            raise _Bad(f"{where} repeats the value {value}; each answer needs its own value")
        seen.add(value)
        choices.append(Choice(str(text).strip(), int(value)))
    return choices


def _items(raw, shared: Optional[List[Choice]]) -> List[Item]:
    if not isinstance(raw, list) or not raw:
        raise _Bad("items must be a list of at least one item")
    items: List[Item] = []
    keys = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise _Bad("each item must be a mapping with key and text")
        key = entry.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key.strip()):
            raise _Bad(f"item key {key!r} must be lower-case letters, digits, and underscores")
        key = key.strip()
        if key in keys:
            raise _Bad(f"two items share the key '{key}'")
        keys.add(key)
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            raise _Bad(f"item '{key}' needs text")
        asks = _asks_for_identifying(text)
        if asks:
            raise _Bad(f"item '{key}' asks for identifying details ({asks}); instruments must not collect them")
        choices = _choices(entry["choices"], f"choices of item '{key}'") if entry.get("choices") is not None else shared
        if not choices:
            raise _Bad(f"item '{key}' has no choices, and the instrument sets no shared choices")
        flipped = entry.get("reversed", False)
        if not isinstance(flipped, bool):
            raise _Bad(f"item '{key}': reversed must be true or false")
        items.append(Item(key=key, text=text.strip(), choices=choices, reversed=flipped))
    return items


def _subscales(raw, items: List[Item]) -> List[Subscale]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _Bad("subscales must be a list")
    known = {i.key: i for i in items}
    scales: List[Subscale] = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise _Bad("each subscale must be a mapping with key, name, and items")
        key = entry.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key.strip()):
            raise _Bad(f"subscale key {key!r} must be lower-case letters, digits, and underscores")
        key = key.strip()
        if key in seen:
            raise _Bad(f"two subscales share the key '{key}'")
        seen.add(key)
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _Bad(f"subscale '{key}' needs a name")
        members = entry.get("items")
        if not isinstance(members, list) or not members:
            raise _Bad(f"subscale '{key}' must list at least one item")
        item_keys = []
        for member in members:
            if member not in known:
                raise _Bad(f"subscale '{key}' names the item '{member}', which this instrument does not have")
            item_keys.append(str(member))
        scales.append(Subscale(key=key, name=name.strip(), item_keys=item_keys,
                               minimum=sum(known[k].minimum for k in item_keys),
                               maximum=sum(known[k].maximum for k in item_keys)))
    return scales


def _missing(raw, item_count: int):
    if raw is None:
        return item_count, False                              # by default every item must be answered
    if not isinstance(raw, dict):
        raise _Bad("missing must be a mapping with minimum_answered and replace_with_mean")
    minimum = raw.get("minimum_answered", item_count)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 1 <= minimum <= item_count:
        raise _Bad(f"minimum_answered must be a whole number between 1 and the number of items ({item_count})")
    replace = raw.get("replace_with_mean", False)
    if not isinstance(replace, bool):
        raise _Bad("replace_with_mean must be true or false")
    return minimum, replace


def _asks_for_identifying(text: str) -> str:
    lowered = text.lower()
    return next((word for word in IDENTIFYING if word in lowered), "")
