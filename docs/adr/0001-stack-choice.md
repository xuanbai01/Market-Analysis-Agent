# ADR 0001: FastAPI + async SQLAlchemy + PostgreSQL

**Status:** Accepted
**Date:** 2026-04-23
**Deciders:** xuanbai01

## Context

Project is a market analysis agent aggregating OHLCV data, news, and sentiment for retail/prosumer traders (see [`design_doc.md`](../../design_doc.md)). Three realities drive the stack decision:

1. **The hot path is external I/O, not CPU.** Every interesting request will eventually call an LLM (OpenAI or Claude), a market-data provider (yfinance today, Polygon later), a vector store (Pinecone), and a cache (Redis). If the runtime can't overlap those waits, latency is the sum of them; if it can, latency is roughly the max.
2. **The LLM/RAG tooling is Python-first.** LangChain, llama-index, the OpenAI and Anthropic SDKs, tiktoken, sentence-transformers — all land in Python before (or instead of) other languages. Picking a non-Python backend means either writing a Python sidecar or accepting second-tier library support.
3. **Budget is $50–80/mo total.** The runtime and managed-DB cost line items have to leave headroom for LLM tokens and vector-store rows. Ruling out anything that needs big per-node overhead (K8s, always-on Lambda warm pools, etc.).

## Options considered

### Option 1: FastAPI + SQLAlchemy 2.0 async + PostgreSQL *(chosen)*
- **Pros:**
  - Native async end-to-end (ASGI server, async SQLAlchemy via asyncpg, `httpx.AsyncClient` for providers).
  - Pydantic v2 validation at route boundaries gives us RFC-7807 422s for free.
  - Auto-generated OpenAPI docs at `/docs` — a discoverable, live API surface is half the portfolio value.
  - Python ecosystem for LLM / RAG / data tooling is the deepest available.
  - Postgres specifically: `ON CONFLICT DO UPDATE` (already used for candle upserts), `TIMESTAMPTZ`, JSONB columns for flexible LLM output storage, and a clean path to TimescaleDB for time-series if we ever need it.
- **Cons:**
  - Less batteries-included than Django — we've already paid the price of choosing our own migrations (Alembic), auth (deferred), and admin (none) stories.
  - Async stack traces are slightly harder to read than sync ones.
  - Debugging requires understanding the event loop; small foot-guns around sync libs that block (we hit one already — yfinance is sync, wrapped in `asyncio.to_thread`).

### Option 2: Django + DRF + Postgres
- **Pros:** Batteries included (auth, admin, migrations, forms, ORM). Massive community. Mature everything.
- **Cons:** Django's async story is still bolt-on (`async def` views work, ORM async is limited, middleware stack mostly sync). For a product whose hot path is "call four external APIs in parallel," that's the wrong fit. DRF layer adds friction for OpenAPI generation compared to FastAPI's native schema export.

### Option 3: Flask + SQLAlchemy (sync) + Postgres
- **Pros:** Simplest Python web story. Everyone knows Flask.
- **Cons:** Sync-only without extra machinery. To do parallel LLM + market + news calls you'd need threads, which interact poorly with SQLAlchemy's connection pool unless carefully done. Not worth the operational tax.

### Option 4: Node.js/TypeScript (Fastify + Prisma + Postgres)
- **Pros:** Single language across eventual web dashboard + backend. Prisma's migrations and types are excellent.
- **Cons:** Second-class LLM ecosystem (LangChain.js is real but trails Python; most RAG papers ship Python reference code). Would force a Python sidecar for any serious agent orchestration.

### Option 5: Go (chi/fiber + sqlx) + Postgres
- **Pros:** Fast, cheap, great concurrency model, small binaries, trivial deploys.
- **Cons:** Weakest LLM/RAG ecosystem of the options. Same sidecar problem as Node. Gains (perf, cost) don't matter at this scale; losses (library coverage) do.

## Decision

**FastAPI + async SQLAlchemy 2.0 + PostgreSQL.**

The shape of this product is "Python glue around async external calls with a DB at the bottom." FastAPI+async-SQLAlchemy is the lowest-friction combination for that shape in 2026, and the Python LLM ecosystem is a moat big enough to outweigh the ergonomic losses vs Django's batteries or Go's performance.

## Consequences

### Easier
- Plug-and-play LangChain, OpenAI/Anthropic SDKs, Pinecone, sentence-transformers — all first-class Python.
- OpenAPI docs auto-generated; no separate Swagger/Postman spec to maintain.
- Pydantic at the boundary means schema drift between API and validation is impossible.
- Async all the way down — fanning out LLM + market + news calls is trivial (`asyncio.gather`).
- Postgres-specific tricks we already use: `ON CONFLICT (symbol, ts, interval) DO UPDATE` in the candle upsert, composite PK + `(symbol, interval, ts DESC)` index for O(1) latest-bar lookup.

### Harder
- No Django admin. Every CRUD tool has to be a real endpoint or a separate `psql` / notebook session.
- Authentication is our problem (when we get there). Likely JWT via `python-jose` or swap in Supabase Auth if we host DB on Supabase.
- Sync-only third-party libs (yfinance is the canonical example) must be wrapped in `asyncio.to_thread` — foot-gun for contributors who don't realize.
- Async debugging + tracing requires care (middleware, correlation IDs).

### Locked-in
- **Python 3.11+.** Type-syntax features (`list[...]`, `X | None`, `datetime.UTC`) assume 3.11. Backporting to 3.10 would be painful.
- **Async throughout.** Mixing a sync DB driver in later would fight the event loop — we'd either end up with sync-over-async threadpools or a full rewrite. Plan accordingly.
- **Postgres-specific features.** `TIMESTAMPTZ`, `ON CONFLICT`, JSONB, and (likely) pgvector for embedding storage. Moving to MySQL/SQLite would mean rewriting the candle upsert and every migration touching these features.

## Deployment target (not part of this decision)

This ADR picks the backend stack, not the deploy target. The design doc names Railway; in practice any of these work with the same Dockerfile and `alembic upgrade head` entrypoint:

- **Fly.io** (preferred for this repo): real free tier (no cold-start spin-down), native Docker deploys, managed Postgres. Fits the $50–80/mo budget comfortably.
- **Render**: zero-ops, ~$14/mo for always-on web + Postgres starter. Easiest "commit and it deploys".
- **Railway**: works, no cheaper than Fly, no unique advantage for this workload.
- **Cloud Run + Cloud SQL**: cheapest at sporadic traffic (scale-to-zero compute), but Cloud SQL is always-on; worth revisiting if usage turns out to be bursty.

Record the concrete pick in a follow-up ADR (0002) when we actually deploy, since the choice depends on observed cost/latency after Phase 2 agents land.

## Revisit when

- LLM workflows shift toward tool-use loops measured in minutes, not requests. Then a queue-first design (Celery / Temporal) matters more than async web framework, and this ADR mostly becomes moot.
- We add a second backend service in a language where FastAPI isn't the natural choice (e.g. a Go indexer, a Rust backtester). Revisit the "one language per service" vs "Python everywhere" tension.
- Traffic outgrows what a single async Python process handles. Unlikely on a $50–80 budget, but if `/v1/analysis` becomes CPU-bound (large RAG reranking), horizontal scaling may force a revisit toward workers + a lighter web tier.
