# Pedigree single container (F-16): FalkorDB v4.22.1 (pinned module, no Docker-in-Docker)
# + the FastAPI service (REST + MCP + static UI). Ubuntu 24.04 LTS, Python 3.12.
#
# Local:
#   docker build -t pedigree .
#   docker run --rm -p 8000:8000 -p 6379:6379 -e PEDIGREE_SEED_DEMO=1 \
#     -e PEDIGREE_ADMIN_TOKEN=choose-one pedigree
#   curl -s localhost:8000/readyz
#
# Render: same image, one web service, PORT/Render-injected env; see README "Deploy".

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    FALKOR_PORT=6379 \
    PEDIGREE_PORT=8000 \
    PATH=/opt/venv/bin:$PATH

# redis-server comes from the pinned falkordblite wheel; curl/bash/ca-certificates fetch the
# pinned FalkorDB module at build time (never `latest`).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        curl ca-certificates bash build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN python3.12 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -e ".[dev,localdb]"

RUN bash scripts/fetch-falkordb.sh \
    && test -x bin/falkordb-4.22.1-x64.so

EXPOSE 8000 6379
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/readyz || exit 1

ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
