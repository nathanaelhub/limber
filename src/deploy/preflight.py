"""
Start-up checks for a hosted Limber (feature 009). The container's entrypoint runs these and refuses
to start the service when one fails, because a hosted therapist app without a password, or a service
on plain HTTP, would expose patient data.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from src.portal import access, admin
from src.ptlog.models import PortalError
from src.ptlog.store import SessionStore


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    optional: bool = False       # reported, but does not stop a deployment (feature 014)


def _key_present(db_path: Path) -> bool:
    import os
    if os.environ.get("PTASSIST_PORTAL_KEY"):
        try:
            access.load_key(access.default_key_path(db_path))
            return True
        except PortalError:
            return False
    path = access.default_key_path(db_path)
    return path.is_file() and len(path.read_bytes()) == 32


def _record_writable(db_path: Path) -> Optional[str]:
    try:
        with SessionStore(db_path).open() as store:
            store.conn.execute("BEGIN IMMEDIATE")
            store.conn.execute("CREATE TABLE IF NOT EXISTS _limber_write_check (x INTEGER)")
            store.conn.execute("DROP TABLE _limber_write_check")
            store.conn.commit()
        return None
    except (sqlite3.Error, OSError) as err:
        return str(err)


def run(db_path: Path, assets_dir: Path, public_origin: Optional[str], therapist_url: Optional[str]) -> List[Check]:
    db_path = Path(db_path)
    checks: List[Check] = []

    write_problem = _record_writable(db_path)
    has_password = False
    if write_problem is None:
        with SessionStore(db_path).open() as store:
            has_password = admin.password_is_set(store)
    checks.append(Check("therapist_password", has_password,
                        "set" if has_password else
                        "No therapist password is set. A hosted therapist app without one would show patient data to "
                        "anyone. Provide it as a secret file and run `deploy init`, or `portal admin set-password`."))
    key_ok = _key_present(db_path)
    checks.append(Check("server_key", key_ok, "present" if key_ok else
                        f"No server key: set PTASSIST_PORTAL_KEY or run `deploy init` to create "
                        f"{access.default_key_path(db_path)} on the persistent volume. Without the same key after a "
                        f"restart, every access code stops working."))
    checks.append(Check("record_writable", write_problem is None, "readable and writable" if write_problem is None else
                        f"The record at {db_path} cannot be written ({write_problem}). Mount the persistent volume "
                        f"read-write for the user running Limber."))
    assets_ok = (Path(assets_dir) / "lightning" / "model.json").is_file()
    checks.append(Check("pose_assets", assets_ok, "present" if assets_ok else
                        "The pose model files are missing, so patients could not run a session. They are fetched and "
                        "hash-checked by `python scripts/fetch_portal_assets.py` (at image build time)."))
    origin = urlparse(public_origin or "")
    origin_ok = origin.scheme == "https" and bool(origin.netloc)
    checks.append(Check("public_origin", origin_ok, public_origin if origin_ok else
                        "The public address must be given and must be https (browsers only allow the camera on https, "
                        "and codes and passwords must not travel in the clear). Example: https://limber.example.org"))
    # Writing out voice notes is optional: an installation without it works, and says so (feature 014).
    from src.media import transcribe
    speech_ok = transcribe.available()
    checks.append(Check("speech_model", speech_ok,
                        f"{transcribe.model_dir()} ({transcribe.model_name()})" if speech_ok else
                        f"Not set up ({transcribe.why_not()}), so voice notes still arrive and play but are "
                        f"not written out. To turn it on: install the speech library and run "
                        f"`python scripts/fetch_speech_model.py --from <downloaded> --into {transcribe.model_dir()}`.",
                        optional=True))
    therapist = urlparse(therapist_url or "")
    therapist_ok = origin_ok and therapist.scheme == "https" and therapist.netloc == origin.netloc and therapist.path not in ("", "/")
    checks.append(Check("therapist_url", therapist_ok, therapist_url if therapist_ok else
                        "The therapist app address must be a path under the public address, for example "
                        "https://limber.example.org/therapist, so it is reachable only through the same proxy."))
    return checks


def initialise(db_path: Path, password_file: Optional[Path] = None) -> List[str]:
    """First boot: create the server key on the volume and set the therapist password from a secret
    file, when they do not exist yet. Returns what was done; never returns or prints a secret."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    done: List[str] = []
    if not _key_present(db_path):
        access.load_key(access.default_key_path(db_path))
        done.append("server key created")
    with SessionStore(db_path).open() as store:
        if not admin.password_is_set(store) and password_file is not None:
            admin.set_password(store, Path(password_file).read_text().rstrip("\n"))
            done.append("therapist password set")
    return done
