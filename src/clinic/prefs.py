"""My settings (feature 019, FR-012): each saved preference turns on one class on the page's `.lb` root, so the
page is right on its first render, before any script runs."""

from __future__ import annotations

from typing import Mapping, Optional

from src.portal.accounts import PREFS

CLASSES = {"larger_text": "lt", "high_contrast": "hc", "reduced_motion": "lm"}
LABELS = {"larger_text": "Larger text", "high_contrast": "Higher contrast", "reduced_motion": "Less motion"}
HINTS = {"larger_text": "Makes all text about one fifth bigger. Pages get longer, nothing is cut off.",
         "high_contrast": "Darker text, stronger lines and darker buttons.",
         "reduced_motion": "Stops loading shimmer and spinning. Progress is shown as text instead."}

assert set(CLASSES) == set(PREFS), "every account preference needs a clinic class"


def classes(prefs: Optional[Mapping[str, bool]]) -> str:
    """The classes for these preferences, in a fixed order; only a real true turns one on."""
    return " ".join(CLASSES[k] for k in PREFS if prefs and prefs.get(k) is True)
