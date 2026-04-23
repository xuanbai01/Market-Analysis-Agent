# Getting Started

Your first hour on this repo. This project already exists (Story 1 scaffolding is in place), so the setup is about running it locally and understanding the code, not bootstrapping from scratch.

## 0. Prerequisites

- Python 3.11+
- Docker + Docker Compose
- [`uv`](https://docs.astral.sh/uv/) (recommended) or plain `pip`
- [`gh` CLI](https://cli.github.com/) authenticated (`gh auth login`) if you'll open PRs
- [Claude Code](https://claude.com/claude-code) installed

## 1. Clone and inspect (5 min)

```bash
git clone https://github.com/xuanbai01/Discord_AI_Chatbot.git
cd Discord_AI_Chatbot
```

Read, in this order:
1. `design_doc.md` — what this project is and where it's going
2. `CLAUDE.md` — modular docs index and current-state summary
3. `docs/architecture.md` — what exists today vs. what's planned

## 2. Environment file (2 min)

Copy the existing `.env` (or ask the repo owner for one). Minimum keys:

```
APP_ENV=dev
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/marketdb
TZ=America/New_York
```

**Never commit a real `.env`.** It is in `.gitignore`.

## 3. Bring up the stack (5 min)

```bash
docker compose up -d db              # just Postgres
uv sync                              # install deps
uv run uvicorn app.main:app --reload # API on :8000
```

Verify:
- `curl http://localhost:8000/` → `{"message":"Hello from Market Analysis Agent"}`
- `curl http://localhost:8000/v1/health` → `{"status":"ok","db":true}`
- `curl http://localhost:8000/v1/symbols` → seeded NVDA + SPY rows
- Swagger UI: http://localhost:8000/docs

If `db` is `false` in the health response, Postgres isn't reachable — check `docker compose logs db`.

## 4. Read the roadmap (10 min)

- `tasks/todo.md` for active sprint items
- `design_doc.md` sections 12–15 for phased roadmap and near-term enhancements
- Existing stubs (`app/services/data_ingestion.py`, `app/services/market_repository.py`, `app/services/technicals.py`) mark where the next implementation work lives

## 5. Write your first failing test (15 min)

There is no `tests/` directory yet. Starting one is a worthy first PR:

1. `mkdir tests && touch tests/__init__.py tests/conftest.py`
2. Add `pytest`, `pytest-asyncio`, `httpx` to dev deps.
3. Write `tests/test_health.py` that calls `GET /v1/health` against an `httpx.AsyncClient(app=app)` and asserts the response shape.
4. `uv run pytest -v`.

See [testing.md](testing.md) for the layout and async patterns.

## 6. Branch protection + GitHub App setup (one-time, repo owner)

When the repo is ready for PR workflow:
- Settings → Branches → require PR, require status checks (`Backend — Unit Tests`, `Security — Secrets Scan`, `AI — PR Review`), dismiss stale approvals on new commits.
- Add `ANTHROPIC_API_KEY` as a repo secret so the AI PR review job can run.

## What's next

- [`docs/workflow.md`](workflow.md) — day-to-day rhythm with Claude Code
- [`docs/testing.md`](testing.md) — TDD discipline + async test patterns
- [`docs/security.md`](security.md) — OWASP Top 10 scoped to this stack
- [`docs/conventions.md`](conventions.md) — code style
- [`docs/adr/`](adr/) — architecture decision records (write one for each significant choice)
- [`tasks/todo.md`](../tasks/todo.md) — active sprint
- [`tasks/lessons.md`](../tasks/lessons.md) — capture every correction so the same mistake doesn't repeat
