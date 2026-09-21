"""Download the patient portal's pose assets into interfaces/portal_static/vendor/ (gitignored).

    .venv/bin/python scripts/fetch_portal_assets.py

Patients' browsers must load the pose library and model from Limber itself, never from another
site (spec 007, FR-018). This script is the only place that talks to those sites: it downloads
pinned versions and refuses any file whose SHA-256 differs from the one recorded here on
2026-09-21, when the model comparison in specs/007-online-patient-view/research.md was run.
All assets are Apache-2.0 (TensorFlow.js, pose-detection, MoveNet SinglePose Lightning v4).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "interfaces" / "portal_static" / "vendor"
CDN = "https://cdn.jsdelivr.net/npm/"
HUB = "https://tfhub.dev/google/tfjs-model/movenet/singlepose/lightning/4/"

# relative path -> (url, sha256)
ASSETS: Dict[str, Tuple[str, str]] = {
    "tf-core.min.js": (CDN + "@tensorflow/tfjs-core@4.22.0/dist/tf-core.min.js",
                       "0924438788ff7da57b14d0f7c45a05d81611a5a4b52653da6d065e86d348757c"),
    "tf-converter.min.js": (CDN + "@tensorflow/tfjs-converter@4.22.0/dist/tf-converter.min.js",
                            "0cf35a2982b637997e8cae097c991c0123b7d5393b3d45730aa732b907c6cd1b"),
    "tf-backend-webgl.min.js": (CDN + "@tensorflow/tfjs-backend-webgl@4.22.0/dist/tf-backend-webgl.min.js",
                                "b41fcbb4aee7721af0cc77ecfede60b44ad4ed6d5782a8392b84f774f4359a45"),
    "pose-detection.min.js": (CDN + "@tensorflow-models/pose-detection@2.1.3/dist/pose-detection.min.js",
                              "eedb38254421de21571e88db202382104b98f36de221a94f956d7bd01f43abcd"),
    "lightning/model.json": (HUB + "model.json?tfjs-format=file",
                             "c65a3447162efa0c42af29498a4b151f4415b36ff3ae6fae2b28a32e840dcbfb"),
    "lightning/group1-shard1of2.bin": (HUB + "group1-shard1of2.bin?tfjs-format=file",
                                       "b42c3232bf13b0efc691d3f0693dd3fc74404f709b1deee0a271828af6dbbea2"),
    "lightning/group1-shard2of2.bin": (HUB + "group1-shard2of2.bin?tfjs-format=file",
                                       "8253ab965aa3122c08f331777ca395ce9ca19bb9e7cb278b99de1c46dbdeb6dc"),
}


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 — fixed https URLs above
        return response.read()


def fetch(dest: Path = VENDOR, assets: Dict[str, Tuple[str, str]] = ASSETS,
          download: Callable[[str], bytes] = _download, log: Callable[[str], None] = print) -> List[Path]:
    """Download what is missing or wrong. A file is written only after its hash matches.
    Raises ValueError naming the file when a download does not match its recorded hash."""
    written: List[Path] = []
    for rel, (url, expected) in assets.items():
        target = dest / rel
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            log(f"ok       {rel}")
            continue
        data = download(url)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError(f"{rel}: the download's SHA-256 is {actual}, expected {expected}. Nothing was written "
                             f"for this file; do not use it.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(target)
        log(f"fetched  {rel} ({len(data) // 1024} KB)")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dest", default=str(VENDOR))
    args = parser.parse_args()
    try:
        fetch(Path(args.dest))
    except (ValueError, OSError) as err:
        print(f"Failed: {err}", file=sys.stderr)
        return 1
    print(f"Pose assets are in {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
