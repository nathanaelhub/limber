"""Feature 009 T008 — static checks on the container files. Docker is not needed to run these; they guard
the properties that matter: no secrets in the image, one writer, only the proxy exposed, checks before start."""

import re
from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


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
