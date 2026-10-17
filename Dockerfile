FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH PEDIGREE_CREDENTIALS_DIR=/data/credentials
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && groupadd --gid 10001 pedigree && useradd --uid 10001 --gid pedigree --no-create-home pedigree \
    && mkdir -p /data/credentials && chown -R pedigree:pedigree /data && chmod 700 /data /data/credentials
COPY scripts/entrypoint.sh scripts/seed_demo.py scripts/runtime.py ./scripts/
COPY demo/scenarios ./demo/scenarios
USER 10001:10001
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=10s --timeout=4s --start-period=15s --retries=6 \
    CMD ["sh", "-c", "python -c \"import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/readyz',timeout=3)\""]
ENTRYPOINT ["bash", "scripts/entrypoint.sh"]
