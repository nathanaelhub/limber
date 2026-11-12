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


# ---- issue #53: tfhub.dev sometimes answers 404; the same files are in Kaggle's archive ---------------------------

def _archive(files):
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_a_failed_download_falls_back_to_the_mirror_archive_once(tmp_path):
    shard, model = b"weights", b'{"model": 1}'
    assets = {"lightning/model.json": ("https://hub.invalid/model.json", hashlib.sha256(model).hexdigest()),
              "lightning/shard.bin": ("https://hub.invalid/shard.bin", hashlib.sha256(shard).hexdigest())}
    mirrors = {"lightning/": "https://mirror.invalid/movenet.tar.gz"}
    archive = _archive({"model.json": model, "shard.bin": shard})
    calls = []

    def download(url):
        calls.append(url)
        if "hub.invalid" in url:
            raise OSError("HTTP Error 404: Not Found")
        return archive

    written = fetcher.fetch(tmp_path, assets, download, log=lambda _m: None, mirrors=mirrors)
    assert len(written) == 2 and (tmp_path / "lightning/shard.bin").read_bytes() == shard
    assert calls.count("https://mirror.invalid/movenet.tar.gz") == 1          # the archive is fetched once


def test_the_mirror_is_held_to_the_same_hash(tmp_path):
    assets = {"lightning/model.json": ("https://hub.invalid/model.json", hashlib.sha256(b"real").hexdigest())}
    archive = _archive({"model.json": b"tampered"})

    def download(url):
        if "hub.invalid" in url:
            raise OSError("HTTP Error 404")
        return archive
    with pytest.raises(ValueError):
        fetcher.fetch(tmp_path, assets, download, log=lambda _m: None, mirrors={"lightning/": "https://m.invalid/a"})
    assert not (tmp_path / "lightning/model.json").exists()


def test_a_wrong_hash_from_the_main_source_is_refused_not_retried(tmp_path):
    """A mismatch could mean tampering, so it stops the install rather than trying elsewhere."""
    assets = {"lightning/model.json": ("https://hub.invalid/model.json", hashlib.sha256(b"real").hexdigest())}
    calls = []

    def download(url):
        calls.append(url)
        return b"something else"
    with pytest.raises(ValueError):
        fetcher.fetch(tmp_path, assets, download, log=lambda _m: None, mirrors={"lightning/": "https://m.invalid/a"})
    assert calls == ["https://hub.invalid/model.json"]


def test_the_model_files_have_a_mirror():
    assert all(any(rel.startswith(p) for p in fetcher.MIRRORS) for rel in fetcher.ASSETS if rel.startswith("lightning/"))


def test_downloads_name_themselves(monkeypatch):
    """The actual cause of #53: tfhub.dev and Kaggle answer 404 to Python's default User-Agent (Python-urllib)."""
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"ok"

    def urlopen(request, timeout):
        seen["ua"] = request.get_header("User-agent")
        return Response()
    monkeypatch.setattr(fetcher.urllib.request, "urlopen", urlopen)
    assert fetcher._download("https://example.invalid/x") == b"ok"
    assert seen["ua"] and "urllib" not in seen["ua"].lower()
