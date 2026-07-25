FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependency layer first so code edits do not invalidate the install cache.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY eval ./eval
COPY scripts ./scripts

EXPOSE 8000

# Railway (and most PaaS) inject $PORT; default to 8000 for local runs.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
