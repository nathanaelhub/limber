#!/bin/sh
# Start Limber only in a safe configuration (feature 009). Secrets come from files or the environment,
# never from the image. Nothing here prints a secret.
set -eu

: "${LIMBER_PUBLIC_ORIGIN:?Set LIMBER_PUBLIC_ORIGIN to the https address of this installation}"
THERAPIST_URL="${LIMBER_PUBLIC_ORIGIN%/}/therapist"
cd /app

# First boot: create the server key on the volume; set the therapist password from the mounted secret.
python interfaces/cli.py deploy init ${LIMBER_THERAPIST_PASSWORD_FILE:+--password-file "$LIMBER_THERAPIST_PASSWORD_FILE"}

# Refuse to start without a therapist password, a server key, a writable record, pose assets, and https.
python interfaces/cli.py deploy preflight --public-origin "$LIMBER_PUBLIC_ORIGIN" --therapist-url "$THERAPIST_URL"

# The therapist app, reachable only through the proxy under /therapist, and gated by the therapist sign-in.
streamlit run interfaces/app.py --server.port 8501 --server.address 0.0.0.0 --server.baseUrlPath therapist \
    --server.headless true --browser.gatherUsageStats false --server.enableXsrfProtection true &

# The patient service and front page. Exactly one instance may write the record.
exec python interfaces/cli.py portal serve --host 0.0.0.0 --port 8600 --insecure-http \
    --public-origin "$LIMBER_PUBLIC_ORIGIN" --trust-proxy --therapist-url "$THERAPIST_URL"
