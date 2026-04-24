# TODO

Active sprint for the Market Analysis Agent. Reference: [`design_doc.md`](../design_doc.md) phases 1–4.

## In progress

-

## Up next (Story 2 — real market ingest)

- [x] Stand up a `tests/` directory with `conftest.py`, async client fixture, rollback-per-test DB fixture
- [x] Add `pytest`, `pytest-asyncio`, `ruff` pins to dev deps (`pyproject.toml [tool.uv] dev-dependencies`) and `uv sync`
- [x] Write tests for `GET /v1/health`, `GET /v1/symbols`, `GET /v1/news` (happy path + 404 + 422)
- [x] Wire Alembic for schema migrations and add a `candles` table (ts, symbol, open/high/low/close/volume, interval)
- [x] Implement `ingest_market_data` in [app/services/data_ingestion.py](../app/services/data_ingestion.py) with yfinance as the first provider; log service id, input, output shape, latency per [security.md#a09](../docs/security.md#a09)
- [x] Replace the fake bar in [app/services/market_repository.py](../app/services/market_repository.py) with a real query against `candles`
- [x] Compute RSI / SMA20 / SMA50 / SMA200 in [app/services/technicals.py](../app/services/technicals.py) from recent `candles`
- [x] Write first ADR: [`docs/adr/0001-stack-choice.md`](../docs/adr/0001-stack-choice.md) (FastAPI + async SQLAlchemy + Postgres)

## Up next (MVP deploy — follow docs/deployment.md)

- [ ] Create Neon project → grab `DATABASE_URL` (convert scheme to `postgresql+asyncpg://`)
- [ ] `fly launch --no-deploy --copy-config --name market-analysis-agent --region iad`
- [ ] `fly secrets set DATABASE_URL="..."`
- [ ] `fly deploy` — verify `/v1/health`, `/v1/symbols`, `/docs`
- [ ] `fly tokens create deploy --name github-actions --expiry 8760h` → add as `FLY_API_TOKEN` repo secret
- [ ] Write ADR 0003 if anything about the deploy surprises us vs ADR 0002's predictions

## Up next (cross-cutting)

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
