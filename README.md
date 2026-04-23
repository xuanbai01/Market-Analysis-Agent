# Market Analysis Agent

A production-oriented financial market analysis backend. Aggregates OHLCV market data, news, and sentiment for US equities and commodities, then runs a multi-agent RAG pipeline to produce analysis, forecasts, and trading strategies. Designed to run on a **$50–80/month** infra budget.

> **Status:** early scaffolding. The routing, error handling, DB layer, and test harness are in place; the ingestion pipeline, RAG layer, and agent stack are next. See [tasks/todo.md](tasks/todo.md) for the active sprint and [design_doc.md](design_doc.md) for the full system design.

## What this is (and isn't)

| | |
|---|---|
| **Is** | A FastAPI + async SQLAlchemy backend for market + news data, targeting retail/prosumer traders doing self-directed analysis. Multi-agent orchestration (LangChain) and RAG (time-weighted retrieval from Pinecone) land in Phase 2. |
| **Isn't** | A Discord bot. The repo's old name (`Discord_AI_Chatbot`) is historical — Discord is one of several planned client surfaces (REST API, web dashboard, Discord), not the product. |
| **Isn't** | A trading execution system. Every response ships with "this is not investment advice" — analysis only. |

## Quickstart

```bash
# 1. Clone
git clone https://github.com/xuanbai01/Market-Analysis-Agent.git
cd Market-Analysis-Agent

# 2. Environment
cp .env.example .env              # dev defaults, no real secrets required

# 3. Database
docker compose up -d db            # Postgres 15 on :5432

# 4. Install + migrate + run
uv sync                            # install pinned deps (or `pip install -e .`)
uv run alembic upgrade head        # apply schema + seed NVDA/SPY
uv run uvicorn app.main:app --reload
```

Verify:

- `curl http://localhost:8000/v1/health` → `{"status":"ok","db":true}`
- `curl http://localhost:8000/v1/symbols` → seeded NVDA + SPY rows
- Swagger UI: <http://localhost:8000/docs>

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for the full first-hour checklist.

## What works today

| Endpoint | State |
|---|---|
| `GET /v1/health` | ✅ Real — pings the DB |
| `GET /v1/symbols`, `POST /v1/symbols` | ✅ Real |
| `GET /v1/news`, `GET /v1/news/{id}` | ✅ Real (list, detail, 404 as RFC 7807 `problem+json`) |
| `POST /v1/news/ingest` | 🟡 No-op stub |
| `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ Real (yfinance ingest with upsert → `candles`; latest-bar and date-range queries) |
| `POST /v1/analysis`, `GET /v1/reports/daily/latest`, `GET /v1/forecasts/{symbol}` | ❌ `501 Not Implemented` |

All errors are serialized as [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](app/core/errors.py).

## Architecture at a glance

```
FastAPI router  ─▶  services / repositories
                         │
                         ▶  SQLAlchemy 2.0 async ORM  ─▶  Postgres
                         ▶  (future) yfinance / Polygon.io / NewsAPI / Reddit
                         ▶  (future) OpenAI GPT-4o-mini / Claude Haiku
                         ▶  (future) Pinecone vector store for RAG
```

- **Language:** Python 3.11, FastAPI 0.115, SQLAlchemy 2.0 (async + asyncpg)
- **DB:** Postgres 15 locally via Docker; Supabase managed in production
- **LLM (planned):** GPT-4o-mini primary, Claude Haiku fallback
- **RAG (planned):** Pinecone free tier, time-weighted retrieval (`score × e^(-λ × hours)`)
- **Agents (planned):** LangChain with Market / News / Strategy subagents
- **Queue (planned):** Celery + Redis (Upstash free tier)
- **Hosting (planned):** Railway.com

Full detail in [docs/architecture.md](docs/architecture.md) and [design_doc.md](design_doc.md).

## Repository layout

```
/
├── app/                         # FastAPI application
│   ├── main.py                  # app factory + router mounting
│   ├── core/                    # settings, logging, RFC 7807 error handling
│   ├── api/v1/
│   │   ├── dependencies.py      # DB session DI
│   │   └── routers/             # one file per route group
│   ├── db/
│   │   ├── session.py           # async engine + sessionmaker
│   │   └── models/              # SQLAlchemy models
│   ├── schemas/                 # Pydantic request/response models
│   └── services/                # repositories, ingestion, technicals
├── alembic/                     # schema migrations (Alembic, async mode)
│   ├── env.py
│   └── versions/                # one file per migration; `alembic upgrade head` applies all
├── tests/                       # pytest-asyncio; function-scoped DB with SAVEPOINT rollback
├── docs/                        # architecture, security, testing, commands, ADRs, PRD template
├── tasks/                       # active sprint (todo.md) + lessons learned
├── design_doc.md                # long-form system design (read this first)
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Development

| Task | Command |
|---|---|
| Run dev server | `uv run uvicorn app.main:app --reload` |
| Run tests | `uv run pytest -v` (requires reachable Postgres at `DATABASE_URL`) |
| Lint | `uv run ruff check app tests` |
| Auto-fix lint | `uv run ruff check --fix app tests` |

More commands in [docs/commands.md](docs/commands.md).

## CI

Every PR runs (see [.github/workflows/ci.yml](.github/workflows/ci.yml)):

- **Backend — Unit Tests:** `ruff` + `pytest` against an ephemeral Postgres service container.
- **Secrets Scan (Gitleaks):** blocks committed secrets.
- **AI PR Review (Claude):** posts an inline review on the PR.

## Contributing

This is a personal learning / portfolio project, but PRs are welcome. If you're opening one:

1. Read [docs/workflow.md](docs/workflow.md) — TDD is non-negotiable for business logic.
2. Read [docs/security.md](docs/security.md) — especially A09 on logging every external call.
3. Open a PR against `main`. The C.L.E.A.R. checklist in [the PR template](.github/pull_request_template.md) is enforced by review.

## License

No license file yet. Treat as all-rights-reserved until one lands.

## Roadmap

Per [design_doc.md](design_doc.md) §12 — phased over roughly 8 weeks:

- **Phase 1 — Core Infrastructure** *(in progress)*: FastAPI scaffold ✅ · tests ✅ · Alembic + real OHLCV ingest · technicals (RSI, SMA20/50/200) · MVP deploy
- **Phase 2 — Agent Development:** Market / News / Strategy agents, time-weighted RAG, LangChain orchestration
- **Phase 3 — Production Features:** caching, rate limiting, monitoring, Discord bot client
- **Phase 4 — Optimization:** perf tuning, cost audit, security audit, load testing
