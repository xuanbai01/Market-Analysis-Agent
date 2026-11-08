# Getting Started

Run the whole stack locally — Postgres, the FastAPI backend, the React dashboard, and the test suites — then read the troubleshooting section, which collects every setup problem this project has actually hit.

## 0. Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — installs Python 3.11 itself from `.python-version`
- Node.js 22 (the frontend toolchain is Vite 5 / Vitest 2 / ESLint 8)
- Docker Desktop (or any Docker engine) for Postgres
- [`gh` CLI](https://cli.github.com/), authenticated (`gh auth login`), if you'll open PRs

## 1. Environment file

```bash
cp .env.example .env
```

The defaults run everything locally with no API keys. To generate research reports you need one LLM key: `ANTHROPIC_API_KEY` with the default `LLM_PROVIDER=anthropic`, or `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY` ([ADR 0006](adr/0006-pluggable-llm-provider.md)). `FRED_API_KEY` and `NEWSAPI_KEY` are optional — those sections degrade without them. **Never commit `.env`** (it's gitignored).

## 2. Database

```bash
docker compose up -d db              # Postgres 15 on :5432
uv sync                              # Python 3.11 + pinned deps
uv run alembic upgrade head          # schema + seed rows in marketdb
```

The first start creates two databases: `marketdb` (the app) and `test_db` (the test suite drops and recreates tables there, so never point tests at `marketdb`). Data lives in the named volume `pgdata`, so `docker compose down` keeps it; `docker compose down -v` wipes it.

## 3. Backend

```bash
uv run uvicorn app.main:app --reload # API on :8000
```

- `curl http://localhost:8000/v1/health` → `{"status":"ok","db":true}`
- Swagger UI: <http://localhost:8000/docs>
- A full report: `curl -X POST http://localhost:8000/v1/research/AAPL` (~30–90 s cold; needs an LLM key)

## 4. Frontend

```bash
cd frontend
npm ci
echo "VITE_BACKEND_URL=http://localhost:8000" > .env.local
npm run dev                          # dashboard on :5173
```

The login screen asks for the backend's `BACKEND_SHARED_SECRET`. Locally that's empty (auth off), so any value gets you in. The backend only answers the browser cross-origin when `FRONTEND_ORIGIN=http://localhost:5173` is set in `.env` (the example file sets it).

## 5. Tests and lint

```bash
# backend — the same commands CI runs
APP_ENV=test DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/test_db uv run pytest -q
uv run ruff check app tests

# frontend
cd frontend && npm run lint && npm run typecheck && npm test

# live LLM eval — costs money, needs the active provider's key; never runs by default
uv run pytest -m live_llm tests/evals -s
```

## 6. Troubleshooting

- **Port 5432 is taken (Windows).** A native Postgres service (e.g. `postgresql-x64-18`) silently wins the port and Docker maps to another. Check `docker ps`; if you see `0.0.0.0:5433->5432/tcp`, either `Stop-Service postgresql-x64-18` and `docker compose up -d db` again, or point `DATABASE_URL` at `:5433`.
- **alembic / uvicorn hangs or fails with `ConnectionRefusedError`.** Check `DATABASE_URL` in `.env`: an old Neon URL (`...neon.tech...?sslmode=require`, `_create_ssl_connection` in tracebacks) when you meant local Docker. And check Docker Desktop is actually running.
- **The app refuses to start with `extra_forbidden`.** `.env` has a key `Settings` doesn't know (typo, or a key from a newer branch). Pydantic prints the offending *value* in that error — so if the key is a secret, rotate it, and add new settings to `app/core/settings.py` before adding them to `.env`.
- **A report looks stale.** Reports are cached for 7 days. Use `?refresh=true`, or set `RESEARCH_CACHE_MAX_AGE_HOURS=0` while debugging.
- **The dashboard shows impossible data.** Browser extensions can rewrite responses; retry in a private window before debugging the backend.
- **Vite serves stale code in a `.claude/worktrees/...` checkout.** The file watcher misses edits there; trust `npm test` + `npm run build` (see `tasks/lessons.md`).
- **Tests pass locally but the deploy breaks.** The Dockerfile installs its own dependency list; add new runtime deps there too (`tests/test_dockerfile_deps.py` enforces it, and CI boots the image).

## What's next

- [`tasks/todo.md`](../tasks/todo.md) — active plan; [`tasks/lessons.md`](../tasks/lessons.md) — past mistakes, read before non-trivial work
- [`design_doc.md`](../design_doc.md) and [`docs/architecture.md`](architecture.md) — what exists and why
- [`docs/workflow.md`](workflow.md), [`docs/testing.md`](testing.md), [`docs/security.md`](security.md), [`docs/conventions.md`](conventions.md)
- [`docs/adr/`](adr/) — architecture decision records
