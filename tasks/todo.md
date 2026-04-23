# TODO

Active sprint for the Market Analysis Agent. Reference: [`design_doc.md`](../design_doc.md) phases 1–4.

## In progress

-

## Up next (Story 2 — real market ingest)

- [ ] Stand up a `tests/` directory with `conftest.py`, async client fixture, rollback-per-test DB fixture
- [ ] Add `pytest`, `pytest-asyncio`, `httpx`, `ruff` to dev deps (`pyproject.toml [tool.uv] dev-dependencies`) and `uv sync`
- [ ] Write failing tests for `GET /v1/health`, `GET /v1/symbols`, `GET /v1/news` (happy path + 404s)
- [ ] Add a `candles` table (ts, symbol, o/h/l/c/v, interval) to `db/init.sql` + a SQLAlchemy model
- [ ] Implement `ingest_market_data` in [app/services/data_ingestion.py](../app/services/data_ingestion.py) with yfinance as the first provider; log service id, input, output shape, latency per [security.md#a09](../docs/security.md#a09)
- [ ] Replace the fake bar in [app/services/market_repository.py](../app/services/market_repository.py) with a real query against `candles`
- [ ] Compute RSI / SMA20 / SMA50 / SMA200 in [app/services/technicals.py](../app/services/technicals.py) from recent `candles`
- [ ] Write first ADR: `docs/adr/0001-stack-choice.md` (FastAPI + async SQLAlchemy + Postgres)

## Up next (cross-cutting)

- [ ] Wire Alembic for schema migrations (replace the raw `db/init.sql` bootstrap)
- [ ] Add a `news_symbols` join table + symbol tagging so `NewsItemOut.symbols` isn't hardcoded `[]`
- [ ] Turn on branch protection for `main` and add `ANTHROPIC_API_KEY` as a repo secret for the AI PR review job

## Backlog (later phases)

- [ ] News ingest from NewsAPI / RSS / Reddit with MinHash dedup
- [ ] Embedding pipeline + Pinecone writes (RAG infra)
- [ ] Time-weighted retrieval (semantic score × exp(-λ × hours_since))
- [ ] Market / News / Strategy agents via LangChain
- [ ] Celery + Redis for scheduled ingestion
- [ ] Auth (deferred until public launch)
- [ ] Discord bot client
- [ ] Rate limiting on LLM-backed endpoints

## Done

- [x] Scaffold FastAPI app with v1 routers and RFC 7807 error handling
- [x] Seed `symbols` and `news_items` schema + docker-compose for Postgres
- [x] Copy Claude Code harness (`CLAUDE.md`, docs, skills, agent, CI) from the project template

## Blocked / waiting

-
