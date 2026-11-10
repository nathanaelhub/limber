#!/bin/sh
# Start Limber only in a safe configuration (feature 009). Secrets come from files or the environment,
# never from the image. Nothing here prints a secret.
set -eu

: "${LIMBER_PUBLIC_ORIGIN:?Set LIMBER_PUBLIC_ORIGIN to the https address of this installation}"
THERAPIST_URL="${LIMBER_PUBLIC_ORIGIN%/}/therapist"
cd /app

# Demo mode (LIMBER_DEMO=1): a simulated clinic in /data/demo.db, seeded on first boot only. Never use it for
# real patients: the demo sign-ins and password are published in the README.
SEED_DEMO=0
if [ "${LIMBER_DEMO:-0}" = "1" ]; then
    export PTASSIST_DB="${LIMBER_DEMO_DB:-/data/demo.db}"
    mkdir -p "$(dirname "$PTASSIST_DB")"
    if [ ! -f "$PTASSIST_DB" ]; then SEED_DEMO=1; fi
fi

# First boot: create the server key on the volume; set the therapist password from the mounted secret.
python interfaces/cli.py deploy init ${LIMBER_THERAPIST_PASSWORD_FILE:+--password-file "$LIMBER_THERAPIST_PASSWORD_FILE"}

if [ "$SEED_DEMO" = "1" ]; then
    python scripts/seed_demo.py --db "$PTASSIST_DB"
    # A public demo spends the clinic's AI key: keep the daily cap per account low.
    python -c "import sys; from pathlib import Path; from src.ptlog.store import SessionStore; from src.assist import assistant
with SessionStore(Path(sys.argv[1])).open() as s: assistant.set_daily_cap(s, int(sys.argv[2]))" "$PTASSIST_DB" "${LIMBER_DEMO_AI_CAP:-10}"
fi

# Refuse to start without a therapist password, a server key, a writable record, pose assets, and https.
python interfaces/cli.py deploy preflight --public-origin "$LIMBER_PUBLIC_ORIGIN" --therapist-url "$THERAPIST_URL"

# The therapist app, reachable only through the proxy under /therapist, and gated by the therapist sign-in.
streamlit run interfaces/app.py --server.port 8501 --server.address 0.0.0.0 --server.baseUrlPath therapist \
    --server.headless true --browser.gatherUsageStats false --server.enableXsrfProtection true &

# One-port hosting (Railway and similar): Caddy on $PORT routes /therapist to 8501 and the rest to 8600.
if [ -n "${PORT:-}" ]; then
    case "$PORT" in 8600|8501) echo "PORT must not be 8600 or 8501, which Limber uses inside the container." >&2; exit 1;; esac
    caddy run --config /app/deploy/Caddyfile.single --adapter caddyfile &
fi

# The patient service and front page. Exactly one instance may write the record.
exec python interfaces/cli.py portal serve --host 0.0.0.0 --port 8600 --insecure-http \
    --public-origin "$LIMBER_PUBLIC_ORIGIN" --trust-proxy --therapist-url "$THERAPIST_URL"
