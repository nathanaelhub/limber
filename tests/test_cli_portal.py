"""Feature 007 T015 — the therapist's command-line controls for home access."""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "interfaces" / "cli.py"
CODE = re.compile(r"\b[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}\b")


def run_cli(env, *args):
    return subprocess.run([sys.executable, str(CLI), *args], env=env, capture_output=True, text=True,
                          cwd=REPO_ROOT, timeout=90)


def out(r):
    return r.stdout + r.stderr


def test_code_create_list_revoke_and_audit(cli_env, tmp_db):
    run_cli(cli_env, "patients", "add", "P-017")
    run_cli(cli_env, "patients", "add", "P-018")
    r = run_cli(cli_env, "portal", "code", "create", "P-017", "--days", "30")
    assert r.returncode == 0, out(r)
    (code,) = CODE.findall(r.stdout)
    assert "valid until" in r.stdout and "shown only once" in r.stdout and "demo and study use only" in r.stdout.lower()
    assert tmp_db.with_name("portal.key").exists()                  # the server key sits beside the record

    listing = run_cli(cli_env, "portal", "code", "list").stdout
    assert re.search(r"P-017\s+active until \d{4}-\d{2}-\d{2}", listing) and re.search(r"P-018\s+none", listing)
    assert code not in listing

    r2 = run_cli(cli_env, "portal", "code", "create", "P-017")        # a new code replaces the old one
    assert CODE.findall(r2.stdout)[0] != code

    assert run_cli(cli_env, "portal", "code", "revoke", "P-017").returncode == 0
    assert re.search(r"P-017\s+revoked", run_cli(cli_env, "portal", "code", "list").stdout)
    assert "No active code" in out(run_cli(cli_env, "portal", "code", "revoke", "P-017"))

    audit = run_cli(cli_env, "portal", "audit", "--patient", "P-017").stdout
    lines = [line for line in audit.splitlines() if " | " in line]
    assert [line.split(" | ")[2].strip() for line in lines] == ["code_revoked", "code_created", "code_created"]
    assert not CODE.findall(audit)


def test_codes_are_refused_for_builtin_discharged_and_unknown(cli_env):
    run_cli(cli_env, "patients", "add", "P-019")
    run_cli(cli_env, "tracker", "discharge", "P-019")
    for pid in ("unassigned", "P-019", "P-404"):
        r = run_cli(cli_env, "portal", "code", "create", pid)
        assert r.returncode == 1 and not CODE.findall(out(r)), pid
    assert run_cli(cli_env, "portal", "code", "create", "P-019", "--days", "0").returncode != 0


def test_serve_refuses_to_leave_this_machine_without_a_secure_connection(cli_env):
    r = run_cli(cli_env, "portal", "serve", "--host", "0.0.0.0", "--port", "8699")
    assert r.returncode == 1 and "secure connection" in out(r) and "--insecure-http" in out(r)
    r = run_cli(cli_env, "portal", "serve", "--certfile", "only-one.pem")
    assert r.returncode == 1 and "both" in out(r).lower()
