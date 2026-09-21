"""Feature 007 T028 — the pose assets are only accepted when their hash matches (no network here)."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_portal_assets.py"
spec = importlib.util.spec_from_file_location("fetch_portal_assets", SCRIPT)
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


def test_writes_only_matching_files_and_skips_good_ones(tmp_path):
    good, other = b"pose library", b"model weights"
    assets = {"a.js": ("https://example.invalid/a.js", hashlib.sha256(good).hexdigest()),
              "m/w.bin": ("https://example.invalid/w.bin", hashlib.sha256(other).hexdigest())}
    calls = []

    def download(url):
        calls.append(url)
        return good if url.endswith("a.js") else other

    written = fetcher.fetch(tmp_path, assets, download, log=lambda _m: None)
    assert [p.relative_to(tmp_path).as_posix() for p in written] == ["a.js", "m/w.bin"]
    assert fetcher.fetch(tmp_path, assets, download, log=lambda _m: None) == [] and len(calls) == 2


def test_a_tampered_download_is_refused_and_not_written(tmp_path):
    assets = {"a.js": ("https://example.invalid/a.js", hashlib.sha256(b"expected").hexdigest())}
    with pytest.raises(ValueError) as err:
        fetcher.fetch(tmp_path, assets, lambda url: b"something else", log=lambda _m: None)
    assert "a.js" in str(err.value) and not (tmp_path / "a.js").exists()


def test_every_recorded_asset_is_pinned_and_hashed():
    for rel, (url, digest) in fetcher.ASSETS.items():
        assert url.startswith("https://") and len(digest) == 64, rel
    assert "lightning/model.json" in fetcher.ASSETS
    assert all("@" in url for rel, (url, _) in fetcher.ASSETS.items() if rel.endswith(".js")), "library versions are pinned"
