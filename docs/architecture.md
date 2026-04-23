# Architecture

Read this before opening source files. The [design_doc.md](../design_doc.md) at the repo root is the long-form system design; this page is the short version of what actually exists in code today and where it's heading.

## Project Overview

A production-grade **Financial Market Analysis Agent** that aggregates real-time market data, news, and sentiment to produce market insights and trading strategies. Uses a RAG architecture with time-weighted relevance scoring and multi-agent orchestration. Target operating cost: **$50–80 / month**.

## Tech Stack

| Layer | Technology | Status |
|---|---|---|
| Language | Python 3.11 | ✅ |
| Web framework | FastAPI 0.115 | ✅ |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | ✅ |
| Config | pydantic-settings | ✅ |
| Database | PostgreSQL 15 (local Docker; Supabase in prod) | ✅ local |
| Task queue | Celery + Redis | 🟡 planned |
| Vector store | Pinecone (free tier) or Qdrant | 🟡 planned |
| Cache | Redis (Upstash free tier) | 🟡 planned |
| Agent framework | LangChain | 🟡 planned |
| LLM | OpenAI GPT-4o-mini (primary), Claude Haiku (fallback) | 🟡 planned |
| Embeddings | OpenAI text-embedding-3-small | 🟡 planned |
| Market data | Polygon.io (primary), yfinance (fallback) | 🟡 planned |
| News | NewsAPI + Benzinga + RSS + Reddit | 🟡 planned |
| Hosting | Railway.com | 🟡 planned |
| Tests | pytest + pytest-asyncio | 🟡 not yet present |
| Lint | ruff | 🟡 configured in pyproject, not enforced |
| CI | GitHub Actions | ✅ (backend tests + Gitleaks + Claude review) |

## Repository Structure

```
/
├── app/                         # FastAPI application
│   ├── main.py                  # App factory, router mounting, error handlers
│   ├── core/                    # settings, logging, error handling (RFC 7807)
│   ├── api/v1/
│   │   ├── dependencies.py      # FastAPI DI (DB session)
│   │   └── routers/             # one file per route group
│   ├── db/
│   │   ├── session.py           # async engine + sessionmaker
│   │   └── models/              # SQLAlchemy models (Base, Symbol, NewsItemModel, Candle)
│   ├── schemas/                 # Pydantic request/response models
│   └── services/                # business logic + repositories
├── alembic/                     # schema migrations (async mode)
│   ├── env.py                   # reads DATABASE_URL from app.core.settings
│   └── versions/                # 0001_baseline.py creates all 3 tables + seeds NVDA/SPY
├── docs/                        # this directory (PRD, ADRs, testing, etc.)
├── tasks/                       # todo.md, lessons.md
├── design_doc.md                # long-form system design (read this first)
├── Dockerfile
├── docker-compose.yml           # postgres + api
├── pyproject.toml
└── CLAUDE.md
```

## Layering Rule

Route handler → Service (or repository) → Model/DB. Never put business logic in a route. Never return an ORM object directly from a route; pass through a Pydantic response schema.

```
FastAPI router  ─▶  services/<domain>_repository.py or <domain>_service.py
                         │
                         ▶  db/models/<domain>.py  (SQLAlchemy)
                         ▶  external providers (yfinance, Polygon, NewsAPI, LLMs)
```

## Data Model (current)

| Entity | Fields | Notes |
|---|---|---|
| `symbols` | `symbol` (PK, varchar 16), `name` (varchar 128, nullable) | Seeded with NVDA, SPY in the baseline migration. |
| `news_items` | `id` (PK, varchar 64), `ts` (timestamptz), `title`, `url`, `source` | Indexed on `ts DESC`. No symbol tagging yet despite the API exposing a `symbols` field. |
| `candles` | composite PK `(symbol, ts, interval)`; `open`, `high`, `low`, `close` (numeric 18/6), `volume` (bigint) | `symbol` has FK → `symbols.symbol` with `ON DELETE CASCADE`. Indexed on `(symbol, interval, ts DESC)` for fast "latest bar" lookups. Append-only; supersede rather than update on restatement. |

**Not yet modeled** (from design doc): news embeddings, user sessions, query history, portfolio positions, strategy backtests.

## Routes (current)

| Group | Routes | Status |
|---|---|---|
| Health | `GET /v1/health` | ✅ real (pings DB) |
| Symbols | `GET /v1/symbols`, `POST /v1/symbols` | ✅ real |
| News | `POST /v1/news/ingest`, `GET /v1/news`, `GET /v1/news/{id}` | GET is real; ingest is a no-op |
| Market | `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ real (yfinance ingest + upsert → `candles`; latest + date-range history queries) |
| Analysis | `POST /v1/analysis` | ❌ 501 |
| Reports | `GET /v1/reports/daily/latest` | ❌ 501 |
| Forecasts | `GET /v1/forecasts/{symbol}` | ❌ 501 |

Errors are serialized as [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](../app/core/errors.py).

## External Integrations (planned)

| Service | Purpose | Failure mode |
|---|---|---|
| Polygon.io | Real-time OHLCV | Fall back to yfinance |
| yfinance | Fallback OHLCV | Log + degrade (return last cached) |
| NewsAPI | News articles | Skip this poll cycle, retry next tick |
| OpenAI GPT-4o-mini | Analysis + strategy synthesis | Fall back to Claude Haiku |
| OpenAI embeddings | Vector store writes | Queue for retry; do not block ingest |
| Pinecone | Vector store for RAG | Degrade to keyword search |
| Redis | Cache + Celery broker | Fail open on cache miss |

Every external call **must** be logged (service id, input shape, output shape, latency, timestamp). See [security.md](security.md#a09) for why this is non-negotiable.

## Architecture Decisions

Big choices go into short ADRs under [docs/adr/](adr/). Ones we know we'll need to write:

- `0001` — FastAPI + async SQLAlchemy over Flask/Django (performance + type hints)
- `0002` — GPT-4o-mini as primary LLM vs GPT-4 (200× cheaper, ≥90% quality for this task)
- `0003` — Pinecone free tier vs self-hosted Qdrant (managed reliability vs zero cost)
- `0004` — Railway.com vs AWS/GCP (simplicity, predictable pricing)
- `0005` — Time-weighted RAG retrieval formula and λ choice

## Open Questions

- When to introduce Celery vs keep ingestion in-process? Trigger: once any ingest endpoint takes >500ms or needs scheduling.
- Will the Discord bot sit in this repo or a separate one? Design doc implies co-located; revisit when bot work starts.
- Where does user/session data live? Supabase Auth or roll our own? No users yet, so deferred.
