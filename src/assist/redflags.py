"""
Red-flag screening on the host (feature 018, FR-005). It runs before anything is drafted, and a message it
flags is never sent to the AI processor for a draft: it needs the therapist directly.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import List

LIST_PATH = Path(__file__).with_name("red_flags.txt")
CURLY = str.maketrans("\u2018\u2019", "''")   # phones type "can’t"; the list is written with a straight apostrophe


@lru_cache(maxsize=1)
def _patterns() -> List[tuple]:
    found = []
    for line in LIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body = line if line.startswith(r"\b") else rf"\b{line}"
        found.append((line, re.compile(body, re.IGNORECASE)))
    return found


def screen(text: str) -> List[str]:
    """The list entries the text trips, in list order; empty when it trips none."""
    if not text:
        return []
    text = text.translate(CURLY)
    return [line for line, pattern in _patterns() if pattern.search(text)]


def found_words(text: str) -> List[str]:
    """What the patient actually wrote that tripped the list, lower-cased and de-duplicated, for the notice."""
    words: List[str] = []
    for _, pattern in _patterns():
        m = pattern.search((text or "").translate(CURLY))
        if m and m.group(0).lower() not in words:
            words.append(m.group(0).lower())
    return [w for w in words if not any(w != other and w in other for other in words)]   # "fall" inside "had a fall"
