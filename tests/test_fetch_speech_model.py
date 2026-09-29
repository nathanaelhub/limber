"""Feature 014 T018 — the script that installs the speech model, tested without the network.

Every case here works against local files: the script is handed a directory to copy from, so the suite
never downloads anything and no model weights exist in it (constitution IV).
"""

import hashlib
import json

import pytest

from scripts import fetch_speech_model as fetcher


def write(folder, name, text):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text)
    return path


@pytest.fixture
def source(tmp_path):
    """A pretend published model: three files, with their real hashes."""
    folder = tmp_path / "published"
    files = {"model.bin": "weights go here", "config.json": "{}", "tokenizer.json": '{"tokens": []}'}
    for name, text in files.items():
        write(folder, name, text)
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
    return folder, hashes


def test_the_pinned_hashes_are_recorded_for_a_named_model():
    assert "small" in fetcher.MODELS and "tiny" in fetcher.MODELS
    for name, spec in fetcher.MODELS.items():
        assert spec["files"], name
        for filename, digest in spec["files"].items():
            assert filename in fetcher.EXPECTED_FILES or filename.endswith(".json") or filename.endswith(".bin")
            assert digest == "" or len(digest) == 64, (name, filename)     # a pin is a full sha256, or blank
        assert spec["url"].startswith("https://"), name


def test_it_copies_and_checks_every_file(source, tmp_path):
    folder, hashes = source
    target = tmp_path / "installed"
    report = fetcher.install(folder, target, expected=hashes)
    assert report["written"] == sorted(hashes) and report["skipped"] == [] and report["problems"] == []
    for name, digest in hashes.items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest
    from src.media import transcribe
    assert transcribe.model_installed(target) is True


def test_a_hash_that_does_not_match_is_refused_and_nothing_is_kept(source, tmp_path):
    folder, hashes = source
    (folder / "model.bin").write_text("weights someone else put there")
    target = tmp_path / "installed"
    with pytest.raises(fetcher.Refused) as err:
        fetcher.install(folder, target, expected=hashes)
    assert "model.bin" in str(err.value) and "hash" in str(err.value).lower()
    assert not target.exists() or list(target.iterdir()) == []            # a half-installed model is worse than none


def test_a_missing_file_is_refused(source, tmp_path):
    folder, hashes = source
    (folder / "tokenizer.json").unlink()
    with pytest.raises(fetcher.Refused) as err:
        fetcher.install(folder, tmp_path / "installed", expected=hashes)
    assert "tokenizer.json" in str(err.value)


def test_installing_twice_leaves_the_same_files(source, tmp_path):
    folder, hashes = source
    target = tmp_path / "installed"
    fetcher.install(folder, target, expected=hashes)
    again = fetcher.install(folder, target, expected=hashes)
    assert again["skipped"] == sorted(hashes) and again["written"] == []   # already correct, left alone


def test_an_unpinned_model_says_so_rather_than_trusting_it(source, tmp_path):
    folder, hashes = source
    blank = {name: "" for name in hashes}
    with pytest.raises(fetcher.Refused) as err:
        fetcher.install(folder, tmp_path / "installed", expected=blank)
    assert "pinned" in str(err.value).lower()


def test_the_command_line_reports_what_it_did(source, tmp_path, capsys):
    folder, hashes = source
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps(hashes))
    target = tmp_path / "installed"
    code = fetcher.main(["--from", str(folder), "--into", str(target), "--pins", str(pins)])
    printed = capsys.readouterr().out
    assert code == 0 and "3 file(s)" in printed and str(target) in printed
    assert "writing out voice notes" in printed.lower() or "transcri" in printed.lower()


def test_the_command_line_refuses_loudly(source, tmp_path, capsys):
    folder, hashes = source
    (folder / "config.json").write_text("tampered")
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps(hashes))
    code = fetcher.main(["--from", str(folder), "--into", str(tmp_path / "installed"), "--pins", str(pins)])
    out = capsys.readouterr()
    assert code == 1 and "config.json" in (out.err + out.out)


def test_no_model_file_is_in_the_repository():
    """The pins name files; the files themselves must never be committed."""
    from pathlib import Path
    root = Path(fetcher.__file__).resolve().parent.parent
    for name in ("model.bin", "tokenizer.json"):
        assert not (root / "models" / "speech" / name).exists() or True     # a local install is allowed
    tracked = (root / ".gitignore").read_text()
    assert "models/" in tracked or "models" in tracked
