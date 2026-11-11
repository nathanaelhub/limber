#!/bin/sh
# Deploy the hosted demo's patient portal to Vercel (feature 020, slice D).
#
#   scripts/deploy_vercel.sh [deploy-folder]
#
# Builds a clean folder from the last commit (so .env, data/ and anything uncommitted can't be uploaded), puts the
# light Vercel requirements and entry point at its root, fetches the pose assets patients' browsers load from
# Limber (hash-checked), links it to the Vercel project limber-demo, and deploys to production. Settings live in
# Vercel, never in the folder. The record and files must already be set up (deploy demo-reset).
set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${1:-"${TMPDIR:-/tmp}/limber-hosted"}
PROJECT=${VERCEL_PROJECT:-limber-demo}
PY=${PYTHON:-"$REPO/.venv/bin/python"}

rm -rf "$OUT"
mkdir -p "$OUT"
git -C "$REPO" archive HEAD | tar -x -C "$OUT"

# Vercel's Python runtime installs the root requirements.txt and loads `app` from index.py.
cp "$REPO/deploy/vercel/requirements.txt" "$OUT/requirements.txt"
cp "$REPO/deploy/vercel/index.py" "$OUT/index.py"
cp "$REPO/deploy/vercel/vercel.json" "$OUT/vercel.json"
cp "$REPO/deploy/vercel/.python-version" "$OUT/.python-version"
cp "$REPO/deploy/vercel/.vercelignore" "$OUT/.vercelignore"
# A Dockerfile at the root would switch Vercel to its container runtime, which the hosted demo doesn't use.
rm -f "$OUT/Dockerfile.vercel" "$OUT/railway.json"

# The pose assets patients' browsers load from Limber: this machine's copies, re-checked against the pinned SHA-256
# list in scripts/fetch_portal_assets.py (their original download site, tfhub.dev, now answers 404).
"$PY" - "$REPO" "$OUT" <<'PYCODE'
import hashlib, shutil, sys
from pathlib import Path
repo, out = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo / "scripts"))
from fetch_portal_assets import ASSETS
src, dest = repo / "interfaces/portal_static/vendor", out / "interfaces/portal_static/vendor"
for rel, (_url, digest) in ASSETS.items():
    data = (src / rel).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        sys.exit(f"Refusing to deploy: vendor/{rel} does not match its pinned SHA-256")
    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
    (dest / rel).write_bytes(data)
print(f"pose assets: {len(ASSETS)} files, hashes checked")
PYCODE

for secret in .env data; do
    if [ -e "$OUT/$secret" ]; then echo "Refusing to deploy: $secret is in the deploy folder." >&2; exit 1; fi
done

cd "$OUT"
vercel link --yes --project "$PROJECT" >/dev/null
rm -f .env.local                                   # vercel link writes one; settings stay in Vercel
vercel deploy --prod --yes
