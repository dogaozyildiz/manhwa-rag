FROM python:3.13-slim

# REQUIRE_API_KEY: deployments must set API_KEY; startup fails otherwise
# (docs/THREAT_MODEL.md T6).
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    REQUIRE_API_KEY=true

# Unprivileged user: code execution in the app must not mean root in the container.
RUN useradd --create-home --uid 10001 app

WORKDIR /app

# Dependency layer first so code edits do not invalidate the install cache.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY eval ./eval
COPY scripts ./scripts

USER app

EXPOSE 8000

# Railway (and most PaaS) inject $PORT; default to 8000 for local runs.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
