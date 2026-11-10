# Limber: patient service (8600) and therapist app (8501, under /therapist) in one image.
# On a one-port host (Railway), set PORT and Caddy inside the image routes both (deploy/Caddyfile.single).
# Build from the repository root:  docker build -f deploy/Dockerfile -t limber .
# NOTE: this image was written on a machine without Docker and has not been built yet; see docs/DEPLOYMENT.md.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PTASSIST_DB=/data/ptassist.db

# OpenCV's runtime libraries; tini reaps the two child processes
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tini curl \
    && rm -rf /var/lib/apt/lists/*

# Caddy, used only in one-port mode (when the platform sets PORT)
COPY --from=caddy:2 /usr/bin/caddy /usr/local/bin/caddy

WORKDIR /app
COPY requirements.txt .
# CPU-only torch keeps the image small; the clinic's camera features stay on the clinic machine.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r requirements.txt

COPY . .
# Pose assets for patients' browsers: fetched and SHA-256 checked at build time, then served by Limber itself.
RUN python scripts/fetch_portal_assets.py
# The pose model for video analysis (gitignored, so a build from git has no copy): fetched and SHA-256 checked.
RUN mkdir -p models && curl -fsSL -o models/yolo11m-pose.pt \
        https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-pose.pt \
    && echo "29b17eaf3a3117cbea906090dbedf9159f7c6a49db58ec8b99ed2dfde1cf6eb2  models/yolo11m-pose.pt" | sha256sum -c -

RUN useradd --create-home --uid 10001 limber && mkdir -p /data && chown -R limber:limber /data /app
USER limber
VOLUME ["/data"]
EXPOSE 8600 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8600/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/deploy/entrypoint.sh"]
