# Limber: patient service (8600) and therapist app (8501, under /therapist) in one image.
# Build from the repository root:  docker build -f deploy/Dockerfile -t limber .
# NOTE: this image was written on a machine without Docker and has not been built yet; see docs/DEPLOYMENT.md.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PTASSIST_DB=/data/ptassist.db

# OpenCV's runtime libraries; tini reaps the two child processes
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 tini curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# CPU-only torch keeps the image small; the clinic's camera features stay on the clinic machine.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r requirements.txt

COPY . .
# Pose assets for patients' browsers: fetched and SHA-256 checked at build time, then served by Limber itself.
RUN python scripts/fetch_portal_assets.py

RUN useradd --create-home --uid 10001 limber && mkdir -p /data && chown -R limber:limber /data /app
USER limber
VOLUME ["/data"]
EXPOSE 8600 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8600/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/deploy/entrypoint.sh"]
