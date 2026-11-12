"""Feature 009 T008 — static checks on the container files. Docker is not needed to run these; they guard
the properties that matter: no secrets in the image, one writer, only the proxy exposed, checks before start."""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy"


def test_dockerfile():
    text = (DEPLOY / "Dockerfile").read_text()
    assert re.search(r"^USER limber", text, re.M) and "useradd" in text                      # not root
    assert "scripts/fetch_portal_assets.py" in text                                          # hash-checked at build time
    assert "HEALTHCHECK" in text and "/api/health" in text
    assert "entrypoint.sh" in text and 'VOLUME ["/data"]' in text
    for forbidden in ("PASSWORD=", "PTASSIST_PORTAL_KEY=", "LIMBER_BACKUP_KEY=", "secrets/"):
        assert forbidden not in text, forbidden


def test_entrypoint_checks_before_anything_starts():
    text = (DEPLOY / "entrypoint.sh").read_text()
    assert text.startswith("#!/bin/sh") and "set -eu" in text
    order = [text.index(marker) for marker in ("deploy init", "deploy preflight", "streamlit run", "portal serve")]
    assert order == sorted(order)
    assert "--server.baseUrlPath therapist" in text and "--trust-proxy" in text
    assert "LIMBER_PUBLIC_ORIGIN:?" in text                                                   # refuses to start without it
    assert "echo $" not in text and "cat /run/secrets" not in text                            # never prints a secret


def test_compose_exposes_only_the_proxy_and_runs_one_writer():
    compose = yaml.safe_load((DEPLOY / "compose.yaml").read_text())
    limber, proxy = compose["services"]["limber"], compose["services"]["proxy"]
    assert "ports" not in limber and sorted(proxy["ports"]) == ["443:443", "80:80"]
    assert limber["deploy"]["replicas"] == 1 and "healthcheck" in limber
    assert limber["volumes"] == ["limber_data:/data"]
    assert limber["secrets"] == ["therapist_password"] and "environment" in limber
    assert not any("PASSWORD=" in str(v) and "FILE" not in str(v) for v in limber.get("environment", {}).items())


def test_caddy_routes_and_keeps_addresses_out_of_the_logs():
    text = (DEPLOY / "Caddyfile").read_text()
    assert re.search(r"handle /therapist\*\s*\{\s*reverse_proxy limber:8501", text)
    assert "reverse_proxy limber:8600" in text and "{$LIMBER_DOMAIN}" in text
    assert "remote_ip delete" in text and "uri query delete" in text                          # no addresses, no ?pass= in logs


def test_secrets_and_local_settings_are_ignored_by_git():
    ignore = (DEPLOY.parent / ".gitignore").read_text()
    assert "deploy/secrets/" in ignore and "deploy/limber.env" in ignore
    example = (DEPLOY / "limber.env.example").read_text()
    assert "https://" in example and "PASSWORD" not in example.upper().replace("NO SECRETS", "")


# ---- a hosted demo on a one-port platform such as Railway -------------------------------------------------

def test_dockerignore_keeps_secrets_and_records_out_of_the_image():
    """The Dockerfile copies the whole repository; without this the image would carry .env (the API key)."""
    ignore = (DEPLOY.parent / ".dockerignore").read_text().split()
    for path in (".env", ".env.*", "data/", ".venv/", ".git/", "deploy/secrets/", "deploy/limber.env"):
        assert path in ignore, path
    assert "tests/" not in ignore and "tests" not in ignore                     # seed_demo.py uses tests/fixtures


def test_single_port_caddy_routes_like_the_two_container_setup():
    text = (DEPLOY / "Caddyfile.single").read_text()
    assert ":{$PORT}" in text and "auto_https off" in text                      # the platform terminates https
    assert re.search(r"handle /therapist\*\s*\{\s*reverse_proxy 127\.0\.0\.1:8501", text)
    assert "reverse_proxy 127.0.0.1:8600" in text
    assert "remote_ip delete" in text and "uri query delete" in text
    assert "COPY --from=caddy:2" in (DEPLOY / "Dockerfile").read_text()


def test_entrypoint_demo_mode_seeds_once_and_still_checks_first():
    text = (DEPLOY / "entrypoint.sh").read_text()
    assert 'LIMBER_DEMO:-' in text and "seed_demo.py --db" in text and "/data/demo.db" in text
    order = [text.index(m) for m in ("deploy init", "seed_demo.py --db", "deploy preflight", "streamlit run",
                                     "portal serve", "caddy run")]
    assert order == sorted(order)
    # A one-port host sends traffic once it can connect, so the port opens only after both apps answer.
    wait = text.index("until curl -fsS")
    assert text.index("portal serve") < wait < text.index("exec caddy run")
    assert "127.0.0.1:8600/api/health" in text and "127.0.0.1:8501/therapist/_stcore/health" in text
    assert '[ ! -f "$PTASSIST_DB" ]' in text                                    # never reseeds over the demo record
    assert 'if [ -n "${PORT:-}" ]' in text                                      # one-port mode only when asked


def test_railway_builds_this_dockerfile_with_one_replica():
    import json
    cfg = json.loads((DEPLOY.parent / "railway.json").read_text())
    assert cfg["build"] == {"builder": "DOCKERFILE", "dockerfilePath": "deploy/Dockerfile"}
    assert cfg["deploy"]["healthcheckPath"] == "/api/health" and cfg["deploy"]["numReplicas"] == 1


# ---- the hosted demo on Vercel (Python functions since 020 slice D) ------------------------------------------

def test_no_container_file_switches_vercel_to_its_container_runtime():
    """A Dockerfile.vercel at the root makes Vercel build a container, which keeps one record per instance and
    signs people out (020). The hosted demo runs as Python functions from deploy/vercel/."""
    root = DEPLOY.parent
    assert not (root / "Dockerfile.vercel").exists() and not (root / "Containerfile.vercel").exists()
    assert (DEPLOY / "vercel" / "index.py").exists() and (DEPLOY / "vercel" / "requirements.txt").exists()


def test_vercel_upload_leaves_secrets_and_records_behind():
    ignore = (DEPLOY.parent / ".vercelignore").read_text().split()
    for path in (".env", ".env.*", "data/", ".venv/", ".git/", "deploy/secrets/", "deploy/limber.env", "models/*.pt"):
        assert path in ignore, path
    assert "tests/" not in ignore


def test_demo_record_path_can_move_to_temporary_storage():
    text = (DEPLOY / "entrypoint.sh").read_text()
    assert 'PTASSIST_DB="${LIMBER_DEMO_DB:-/data/demo.db}"' in text
    assert 'mkdir -p "$(dirname "$PTASSIST_DB")"' in text


def test_vercelignore_never_drops_runtime_code():
    """A bare `exports/` in .vercelignore matched src/ptlog/exports too, and the hosted clinic's exports failed with
    ModuleNotFoundError. Folder patterns are anchored to the top, and no pattern matches anything the app imports."""
    import fnmatch
    import subprocess
    ignore = (REPO / "deploy" / "vercel" / ".vercelignore").read_text().splitlines()
    patterns = [l.strip() for l in ignore if l.strip() and not l.startswith("#")]
    for pattern in patterns:
        if pattern.endswith("/") or "/" in pattern.rstrip("/"):
            assert pattern.startswith("/"), f"{pattern}: anchor folder patterns with a leading /"
    tracked = subprocess.run(["git", "ls-files", "src", "interfaces", "analyze.py"], cwd=REPO, capture_output=True,
                             text=True).stdout.split()
    for path in tracked:
        for pattern in patterns:
            anchored = pattern.lstrip("/").rstrip("/")
            assert not (path == anchored or path.startswith(anchored + "/") or fnmatch.fnmatch(path, anchored)), \
                f"{pattern} would leave {path} out of the hosted bundle"
