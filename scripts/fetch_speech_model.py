#!/usr/bin/env python3
"""Install the speech model Limber uses to write out voice notes (feature 014).

Writing out is optional: Limber runs without it, and voice notes arrive and play either way. This script
is how an owner turns it on, and it exists so that what lands on the host is **known**:

- every file is checked against a hash pinned in this file before it is kept;
- a mismatch refuses the whole install rather than keeping half a model;
- nothing is ever committed to the repository (`models/` is gitignored);
- it can install from a local directory, so the test suite needs no network and no weights.

Usage:

    python scripts/fetch_speech_model.py --model small
    python scripts/fetch_speech_model.py --from /path/to/downloaded --into models/speech

The pins below are **blank until the owner fills them in from a download they have checked themselves**.
That is deliberate: shipping a hash nobody verified would only look like provenance. With a blank pin the
script refuses to install and says so, which is the honest failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = REPO_ROOT / "models" / "speech"
EXPECTED_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
CHUNK = 1024 * 1024

# Known faster-whisper (CTranslate2) models. `files` maps the file name to its pinned SHA-256; a blank
# pin means "not verified here", and the script refuses to install it.
MODELS: Dict[str, dict] = {
    "tiny": {
        "url": "https://huggingface.co/Systran/faster-whisper-tiny",
        "about": "about 75 MB; fastest and least accurate",
        "files": {"model.bin": "", "config.json": "", "tokenizer.json": "", "vocabulary.txt": ""},
    },
    "small": {
        "url": "https://huggingface.co/Systran/faster-whisper-small",
        "about": "about 500 MB; the sensible default on a small host",
        "files": {"model.bin": "", "config.json": "", "tokenizer.json": "", "vocabulary.txt": ""},
    },
}


class Refused(Exception):
    """The install was refused. Nothing is kept: half a model is worse than none."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def install(source: Path, target: Path, expected: Dict[str, str]) -> Dict[str, List[str]]:
    """Copy each named file from `source` to `target`, checking every hash first.

    Nothing is written until every file has been found and checked, so a refusal leaves the target as it
    was rather than half filled."""
    source, target = Path(source), Path(target)
    if not expected:
        raise Refused("No files were named to install.")
    blank = sorted(name for name, digest in expected.items() if not digest)
    if blank:
        raise Refused("These files have no pinned hash, so they cannot be trusted: "
                      + ", ".join(blank)
                      + ". Fill the pins in scripts/fetch_speech_model.py from a download you have "
                        "checked yourself, or pass --pins with the hashes you verified.")
    problems: List[str] = []
    checked: Dict[str, Path] = {}
    for name, digest in sorted(expected.items()):
        candidate = source / name
        if not candidate.is_file():
            problems.append(f"{name} is missing from {source}")
            continue
        actual = sha256(candidate)
        if actual != digest:
            problems.append(f"{name} does not match its pinned hash (expected {digest[:12]}…, "
                            f"got {actual[:12]}…)")
            continue
        checked[name] = candidate
    if problems:
        raise Refused("Refusing to install: " + "; ".join(problems))

    written, skipped = [], []
    target.mkdir(parents=True, exist_ok=True)
    for name, candidate in checked.items():
        destination = target / name
        if destination.is_file() and sha256(destination) == expected[name]:
            skipped.append(name)
            continue
        shutil.copy2(candidate, destination)
        written.append(name)
    return {"written": sorted(written), "skipped": sorted(skipped), "problems": []}


def _pins(model: Optional[str], pins_file: Optional[str]) -> Dict[str, str]:
    if pins_file:
        data = json.loads(Path(pins_file).read_text())
        if not isinstance(data, dict):
            raise Refused("A pins file must be a mapping of file name to sha256.")
        return {str(k): str(v) for k, v in data.items()}
    if model not in MODELS:
        raise Refused(f"Unknown model '{model}'. Choose from: {', '.join(sorted(MODELS))}.")
    return dict(MODELS[model]["files"])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default="small", choices=sorted(MODELS),
                        help="which model's pinned file list to use")
    parser.add_argument("--from", dest="source", required=True, metavar="DIR",
                        help="a directory holding the model files you have already downloaded")
    parser.add_argument("--into", dest="target", default=str(DEFAULT_TARGET), metavar="DIR",
                        help=f"where to install them (default {DEFAULT_TARGET})")
    parser.add_argument("--pins", metavar="FILE",
                        help="a JSON file of name -> sha256 to use instead of the pins in this script")
    args = parser.parse_args(argv)
    try:
        expected = _pins(args.model, args.pins)
        report = install(Path(args.source), Path(args.target), expected)
    except Refused as refused:
        print(str(refused), file=sys.stderr)
        return 1
    except (OSError, ValueError) as err:
        print(f"Could not install: {err}", file=sys.stderr)
        return 1
    kept = len(report["written"]) + len(report["skipped"])
    print(f"Installed {kept} file(s) into {args.target} "
          f"({len(report['written'])} copied, {len(report['skipped'])} already correct).")
    print("Writing out voice notes will be available once the speech library is installed as well "
          "(see docs/DEPLOYMENT.md). Until then Limber says so plainly and voice notes still play.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
