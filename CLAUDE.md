# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

> **Product context:** this repo is a **Financial Market Analysis Agent** — a FastAPI backend that aggregates market data, news, and sentiment to produce analysis, forecasts, and trading strategies via a multi-agent RAG pipeline. The repo name `Discord_AI_Chatbot` is historical; Discord is one of several planned client surfaces, not the product.
>
> **System design:** [`design_doc.md`](design_doc.md) (root) is the source of truth for scope, budget, stack, and roadmap. Read it before making non-trivial changes.
> **Active tasks:** `tasks/todo.md`. Lessons: `tasks/lessons.md`.
> **Architecture Decision Records:** `docs/adr/`.

## How this file works

The `@imports` below pull in modular docs — one concern per file — so a single CLAUDE.md does not balloon. Keep this file short; edit the imported docs instead.

---

@docs/commands.md

@docs/architecture.md

@docs/conventions.md

@docs/testing.md

@docs/security.md

@docs/workflow.md

---

## Current state (Story 1 scaffolding)

- FastAPI app under `app/` with v1 routers mounted in [app/main.py](app/main.py).
- **Working:** `/v1/health`, `/v1/symbols` (GET/POST), `/v1/news` (list + detail).
- **Stubbed (returns fake data or 501):** `/v1/market/*`, `/v1/analysis`, `/v1/reports/daily/latest`, `/v1/forecasts/{symbol}`.
- **Ingestion:** [app/services/data_ingestion.py](app/services/data_ingestion.py) is a no-op.
- **DB:** Postgres via async SQLAlchemy 2.0 + asyncpg. Schema lives in [db/init.sql](db/init.sql); only `symbols` and `news_items` exist.
- **Infra:** local dev via `docker-compose up`. No Redis, Celery, vector DB, LangChain, or Discord bot yet (all on the roadmap).

When making changes, prefer filling in stubs (market repo, ingestion, technicals) over adding new surface area unless the PRD/roadmap asks for it.
