"""
Where uploaded files live (feature 020, FR-004 and FR-005). Local and self-hosted installs keep them in the media
folder next to the record, as always. The hosted demo keeps them in a private Cloudflare R2 bucket, because a
Vercel instance's disk is temporary and not shared.

Every uploaded file is written, read and deleted through this interface, by a path relative to the media folder
(`P-017/<id>.mp4`, `P-017/attachments/<id>.jpg`, `.incoming/<upload>/part-0`). Limber still decides who may see a
file: on R2 a browser gets only a signed link to one file, valid for minutes, after the same checks as before.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Dict, Iterator, List, Optional

SIGNED_SECONDS = 300                  # signed links last five minutes
_R2_SETTINGS = ("LIMBER_R2_ACCOUNT_ID", "LIMBER_R2_BUCKET", "LIMBER_R2_ACCESS_KEY_ID", "LIMBER_R2_SECRET_ACCESS_KEY")
_NO_STORE = "private, no-store"


class NotFound(Exception):
    """No file at that path."""


def _clean(rel: str, allow_empty: bool = False) -> str:
    """A relative path inside the store; anything that could reach outside it is refused."""
    if allow_empty and str(rel) == "":
        return ""
    p = PurePosixPath(str(rel))
    if not str(rel) or p.is_absolute() or ".." in p.parts:
        raise ValueError(f"Not a path inside the media store: {rel!r}")
    return str(p)


class LocalFiles:
    """The media folder on this machine (every install except the hosted demo)."""

    remote = False

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, rel: str) -> Path:
        return self.root / _clean(rel)

    def _ready(self, rel: str) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        for folder in [target.parent, *target.parent.parents]:
            if folder == self.root.parent:
                break
            if folder.is_relative_to(self.root):
                os.chmod(folder, 0o700)
        return target

    def put_bytes(self, rel: str, data: bytes) -> None:
        target = self._ready(rel)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        tmp.replace(target)

    def put_file(self, rel: str, source: Path) -> None:
        target = self._ready(rel)
        os.chmod(source, 0o600)
        shutil.move(str(source), str(target))          # a rename on one disk, a copy across disks

    def get_bytes(self, rel: str) -> bytes:
        try:
            return self.path(rel).read_bytes()
        except FileNotFoundError:
            raise NotFound(rel) from None

    def exists(self, rel: str) -> bool:
        return self.path(rel).is_file()

    def list(self, prefix: str) -> List[str]:
        """Every file under `prefix` ("" for the whole store)."""
        base = self.root / _clean(prefix, allow_empty=True)
        if not base.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())

    def delete(self, rel: str) -> None:
        self.path(rel).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        shutil.rmtree(self.root / _clean(prefix), ignore_errors=True)

    @contextmanager
    def local_path(self, rel: str) -> Iterator[Path]:
        p = self.path(rel)
        if not p.is_file():
            raise NotFound(rel)
        yield p

    def response(self, rel: str, media_type: str, filename: str, headers: Optional[Dict[str, str]] = None):
        """The file itself, or None if it's missing."""
        from starlette.responses import FileResponse
        p = self.path(rel)
        if not p.is_file():
            return None
        return FileResponse(str(p), media_type=media_type, headers={
            "Cache-Control": _NO_STORE, "Content-Security-Policy": "sandbox", "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{filename}"', **(headers or {})})

    def signed_put(self, rel: str, content_type: str) -> str:
        raise NotImplementedError("Local installs receive uploads through Limber itself.")


class R2Files:
    """The hosted demo's private R2 bucket, through its S3-compatible API."""

    remote = True

    def __init__(self, client, bucket: str, prefix: str = "media/", endpoint: str = ""):
        self.client, self.bucket, self.prefix, self.endpoint = client, bucket, prefix, endpoint

    def _key(self, rel: str) -> str:
        return self.prefix + _clean(rel)

    def put_bytes(self, rel: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._key(rel), Body=data)

    def put_file(self, rel: str, source: Path) -> None:
        self.put_bytes(rel, Path(source).read_bytes())
        Path(source).unlink(missing_ok=True)

    def get_bytes(self, rel: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(rel))["Body"].read()
        except Exception as e:  # noqa: BLE001 — boto3 raises its own NoSuchKey; the fake raises NotFound
            if isinstance(e, NotFound) or "NoSuchKey" in type(e).__name__ or "NoSuchKey" in str(e) or "404" in str(e):
                raise NotFound(rel) from None
            raise

    def exists(self, rel: str) -> bool:
        key = self._key(rel)
        return any(o["Key"] == key for o in self._objects(key))

    def _objects(self, key_prefix: str) -> List[dict]:
        found, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": key_prefix}
            if token:
                kw["ContinuationToken"] = token
            page = self.client.list_objects_v2(**kw)
            found += page.get("Contents", [])
            if not page.get("IsTruncated"):
                return found
            token = page.get("NextContinuationToken")

    def list(self, prefix: str) -> List[str]:
        """Every file under `prefix` ("" for the whole store)."""
        return sorted(o["Key"][len(self.prefix):] for o in self._objects(self.prefix + _clean(prefix, allow_empty=True)))

    def delete(self, rel: str) -> None:
        self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": self._key(rel)}]})

    def delete_prefix(self, prefix: str) -> None:
        keys = [o["Key"] for o in self._objects(self._key(prefix))]
        for i in range(0, len(keys), 1000):
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})

    @contextmanager
    def local_path(self, rel: str) -> Iterator[Path]:
        """A temporary copy for tools that need a file (the media probe, transcription); removed afterwards."""
        data = self.get_bytes(rel)
        folder = Path(tempfile.mkdtemp(prefix="limber-"))
        try:
            p = folder / PurePosixPath(_clean(rel)).name
            p.write_bytes(data)
            yield p
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def response(self, rel: str, media_type: str, filename: str, headers: Optional[Dict[str, str]] = None):
        """A redirect to a five-minute signed link for this one file, or None if it's missing. The link carries
        the type, file name and no-store that Limber would have sent itself."""
        from starlette.responses import RedirectResponse
        if not self.exists(rel):
            return None
        url = self.client.generate_presigned_url("get_object", Params={
            "Bucket": self.bucket, "Key": self._key(rel), "ResponseContentType": media_type,
            "ResponseCacheControl": _NO_STORE, "ResponseContentDisposition": f'inline; filename="{filename}"'},
            ExpiresIn=SIGNED_SECONDS)
        return RedirectResponse(url, status_code=302, headers={"Cache-Control": _NO_STORE, "Referrer-Policy": "no-referrer"})

    def signed_put(self, rel: str, content_type: str) -> str:
        """A five-minute link the browser can upload exactly one file of this type to."""
        return self.client.generate_presigned_url("put_object", Params={
            "Bucket": self.bucket, "Key": self._key(rel), "ContentType": content_type}, ExpiresIn=SIGNED_SECONDS)


# ---------------------------------------------------------------- choosing the store

def _r2_settings() -> Optional[Dict[str, str]]:
    values = {k: os.environ.get(k, "").strip() for k in _R2_SETTINGS}
    return values if all(values.values()) else None


def r2_origin() -> Optional[str]:
    """The R2 address a hosted page must allow for media (its content security policy), or None locally."""
    s = _r2_settings()
    return f"https://{s['LIMBER_R2_ACCOUNT_ID']}.r2.cloudflarestorage.com" if s else None


def _s3_client(account: str, key_id: str, secret: str):
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=f"https://{account}.r2.cloudflarestorage.com", region_name="auto",
                        aws_access_key_id=key_id, aws_secret_access_key=secret,
                        config=Config(signature_version="s3v4", retries={"max_attempts": 3}))


_cached: Dict[str, R2Files] = {}


def at(media_dir: Path):
    """The file store for this install: R2 when the LIMBER_R2_* settings are set, else the media folder."""
    s = _r2_settings()
    if s is None:
        return LocalFiles(Path(media_dir))
    key = s["LIMBER_R2_ACCOUNT_ID"] + "/" + s["LIMBER_R2_BUCKET"]
    if key not in _cached:
        client = _s3_client(s["LIMBER_R2_ACCOUNT_ID"], s["LIMBER_R2_ACCESS_KEY_ID"], s["LIMBER_R2_SECRET_ACCESS_KEY"])
        _cached[key] = R2Files(client, s["LIMBER_R2_BUCKET"], "media/", r2_origin())
    return _cached[key]
