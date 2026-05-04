# Development Commands

All commands run from the repo root unless stated otherwise.

## Local stack (Docker Compose)

```bash
docker compose up -d db          # Postgres 15 on :5432 (empty; run `alembic upgrade head` next)
docker compose up --build        # also build + run the FastAPI container on :8000
docker compose down              # stop everything; add -v to wipe the volume
```

## Backend (dev loop, without the API container)

```bash
# If you use uv (preferred):
uv sync                          # install pinned deps from pyproject.toml
uv run uvicorn app.main:app --reload

# Or with pip + a venv:
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # project + dev deps once tests exist
uvicorn app.main:app --reload    # runs on :8000
```

- Swagger UI: http://localhost:8000/docs
- OpenAPI spec: http://localhost:8000/openapi.json
- Root healthcheck: `GET /` · DB healthcheck: `GET /v1/health`

## Tests

Tests live in `tests/` and expect a reachable Postgres at `DATABASE_URL` (by default `localhost:5432/test_db`). The CI job spins one up; locally:

```bash
docker compose up -d db          # or point DATABASE_URL at any other Postgres
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/test_db

uv run pytest -v                       # full suite
uv run pytest tests/test_symbols.py    # one file
uv run pytest -k news -v               # filter by name
uv run pytest --cov=app --cov-report=term-missing
```

Each test runs inside a SAVEPOINT that rolls back, so tests are isolated without dropping/recreating the schema per test.

## Lint / typecheck

```bash
uv run ruff check app tests      # lint (matches what CI runs)
uv run ruff check app tests --fix  # auto-fix
uv run ruff format app tests     # format
uv run mypy app                  # (once mypy config lands)
```

## Database

Schema is managed by Alembic — see [alembic/versions/](../alembic/versions/). A fresh Postgres only has `alembic_version` + the Alembic schema until `alembic upgrade head` runs.

```bash
uv run alembic upgrade head                                 # apply all pending migrations
uv run alembic current                                      # show current revision
uv run alembic history                                      # list all migrations
uv run alembic revision --autogenerate -m "describe change" # generate from model diffs
uv run alembic downgrade -1                                 # roll back one revision
```

After `docker compose up -d db` on a fresh machine, always run `alembic upgrade head` before `uvicorn` — the app expects the schema to exist.

## Pre-push sanity check

Until CI is fully wired, run this before pushing a branch:

```bash
uv run ruff check app tests && uv run pytest -v
```

(Both directories — CI checks `tests/` too, so a clean `app/` alone isn't enough.)
