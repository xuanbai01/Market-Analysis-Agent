# Financial Market Analysis Agent — Design

> **Status:** v2 — **AI Equity Research Assistant**. Live at <https://market-analysis-agent.fly.dev>. Pivoted from the v1 "real-time multi-agent platform" vision in [ADR 0003](docs/adr/0003-pivot-equity-research.md). Report shape settled as **visual-first, delta-driven** in [ADR 0004](docs/adr/0004-visual-first-product-shape.md) — multi-year time series rendered as charts, LLM commentary stays short and stays at judgment-dependent moments. This doc is the single source of truth for current scope, architecture, and roadmap. The v1 design lives in git history.

## Goal

Given a US-equity ticker, return a fully-cited structured research report — valuation, quality, capital allocation, technicals, news, earnings, peers, macro, insider/institutional flows, risk-factor delta — with multi-year time series surfaced as charts on every metric we have history for. The agent calls free-data tools, the schema enforces citations, the eval harness gates regressions.

Two real workflows the system serves:

1. **Long-term value diligence** — main-account research before adding or trimming a position.
2. **Catalyst-aware position sizing** — knowing what just changed (10-K risk-factor diffs, EPS trend, peer outliers, recent material news) before sizing into or out of a name.

Cost target: **$5–15 / month all-in** (free-tier infra + free data + cost-tier-routed LLM). The original $50–80/mo design budget is wide enough to absorb a Sonnet-only synth tier without breaking.

## Scope

**In:** structured equity research reports on US-listed equities. On-demand per request, cached same-day. Reuses Phase 1 ingest for OHLCV + news + technicals.

**Out:** real-time feeds, intraday alerts, scheduled news firehose, Discord client, options copilots without IV data, multi-symbol portfolio orchestration, Reddit sentiment (revisit later if a query genuinely benefits).

## Architecture (current)

```
HTTP request
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ FastAPI 0.115 — async SQLAlchemy 2.0 + asyncpg      │
│ RFC 7807 errors, log_external_call observability    │
└─────────────────────────────────────────────────────┘
    │
    ├──── Existing endpoints ────────────────────────────
    │   /v1/health, /v1/symbols, /v1/news (list/ingest),
    │   /v1/market/{symbol} (latest + history + ingest)
    │
    └──── Planned: POST /v1/research/{symbol} ───────────
              │
              ▼
          ┌──────────────────────────────────────────┐
          │ Default mode: single agent + tools       │
          │  ─ Triage (Haiku 4.5) picks tools        │
          │  ─ Synth (Sonnet 4.6) composes report    │
          │  Both forced-tool with Pydantic schemas  │
          │                                          │
          │ Optional supervisor mode for complex     │
          │ queries — kept as one mode, not the      │
          │ architecture.                            │
          └──────────────────────────────────────────┘
              │
              ▼
          Tool registry (see below)
              │
              ▼
          Pydantic ResearchReport → JSON
```

Layering: `router → service → repository / external`. Business logic never lives in routers. See [docs/architecture.md](docs/architecture.md) for the per-file map.

### Storage

- **Postgres on Neon** (managed, autosuspend). Schema in `alembic/versions/`. Tables: `symbols`, `news_items`, `news_symbols` (join), `candles`. Vector extension + `embeddings` columns added in a future Alembic migration when `search_history` lands.
- **No Redis, no Celery, no scheduled cron.** Re-introduced only if a real workload forces it.

### Hosting

- **Fly.io** — shared-CPU 256 MB machine, primary region IAD, auto-stop. CI deploys on push to `main`. See [ADR 0002](docs/adr/0002-deployment.md) for why Fly + Neon over Railway + Supabase.

## Tech stack (current pins)

| Layer | Tech | Status |
|---|---|---|
| Language | Python 3.11 | ✅ |
| Web framework | FastAPI 0.115 | ✅ |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | ✅ |
| Migrations | Alembic 1.13 | ✅ |
| Validation | Pydantic 2.9 | ✅ |
| LLM provider | Anthropic SDK 0.97 (Claude Haiku 4.5 + Sonnet 4.6) | ✅ |
| Market data | yfinance 1.3 | ✅ |
| News | NewsAPI dev tier + Yahoo per-ticker RSS (feedparser 6.0) | ✅ |
| Database | PostgreSQL 15 (Docker locally; Neon in prod) | ✅ |
| Hosting | Fly.io | ✅ |
| Tests | pytest 8.3 + pytest-asyncio | ✅ |
| Lint | ruff 0.6 | ✅ |
| CI | GitHub Actions (backend tests + Gitleaks + Claude PR review) | ✅ |
| Vector store (planned) | pgvector on Neon | 🟡 |
| Embeddings (planned) | TBD when `search_history` lands | 🟡 |

**Deliberately not used:** OpenAI, LangChain, Celery, Redis, Pinecone. ADR 0003 dropped them; the single-agent-with-tools pattern doesn't need them. Re-introduce only with a documented decision.

## Data model

| Table | Columns | Indexes | Notes |
|---|---|---|---|
| `symbols` | `symbol` (PK), `name` | — | Watchlist. Seeded with NVDA, SPY. |
| `candles` | `(symbol, ts, interval)` PK; OHLCV; FK on `symbol` | `(symbol, interval, ts DESC)` | Append-only; supersede on restate. |
| `news_items` | `id` (`sha256(url)`) PK, `ts`, `title`, `url`, `source` | `ts DESC` | Hash-id collapses duplicates across providers. |
| `news_symbols` | `(news_id, symbol)` composite PK; cascading FKs | `(symbol, news_id)` | Tags articles to one or more symbols. |

**Planned:** `embeddings` column on `news_items` and a `filings` table when `search_history` lands; `option_iv_history` when `compute_options` lands; `research_reports` for the same-day response cache.

## Tool registry

Tools live in `app/services/<tool>.py`. Each follows the same shape: provider-registry pattern, sync provider wrapped in `asyncio.to_thread`, every external call wrapped in `log_external_call`. Tests mock at the provider registry, not at the network.

| Tool | Source | Status |
|---|---|---|
| `fetch_market` | yfinance OHLCV | ✅ |
| `compute_technicals` | in-memory (RSI, SMA20/50/200) | ✅ |
| `fetch_news` | NewsAPI dev tier + Yahoo RSS, symbol tagging | ✅ (PR #13) |
| `fetch_fundamentals` | yfinance .info + financials/cashflow | ✅ (PR #14) |
| `fetch_peers` | curated sector map + yfinance.industry fallback | ✅ (PR #15) |
| `fetch_edgar` | SEC EDGAR generic filing fetcher (disk cache, polite-crawl) | ✅ (PR #17) |
| `parse_filing` | Form 4 / 13F / 10-K Business / 10-K risks YoY diff | ✅ (PRs #19, #21, #22, #23) |
| `fetch_earnings` | yfinance earnings dates + consensus + beat-rate | ✅ (PR #18) |
| `fetch_macro` | FRED API + sector→series map | ✅ (PR #20) |
| `search_history` | pgvector RAG over stored news + filings | indefinitely deferred (ADR 0004) |
| `compute_options` | yfinance option_chain → IV percentile, implied move | indefinitely deferred (ADR 0004) |

**Tool extensions in Phase 3 (active).** Existing tools learn to return multi-year history alongside their point-in-time values: `fetch_fundamentals` (quarterly via yfinance), `fetch_earnings` (~20 quarters), `fetch_macro` (FRED series), plus a new derived `fetch_valuation_history` (rolling P/E / P/S / EV/EBITDA from price + financials). Backwards-compatible — the new history is an optional field on `Claim`. See [ADR 0004](docs/adr/0004-visual-first-product-shape.md) §"Phase 3" for the full plan.

Active sprint tracking: [tasks/todo.md](tasks/todo.md).

## LLM strategy

- **Cost-tier routing.** Triage (Claude Haiku 4.5) picks tools; synth (Claude Sonnet 4.6) composes the report. See [app/services/llm.py](app/services/llm.py). Saves ~60–80% of token cost vs always running on Sonnet, to be re-measured after the agent endpoint ships and documented in a follow-up ADR.
- **Forced-tool pattern with Pydantic schemas.** The model is forced to populate a single `submit_response` tool whose `input_schema` is the Pydantic JSON schema. Output is either a parseable `tool_use` block or an SDK exception — no JSON-string parsing, no free-form prose path.
- **Prompt caching.** System blocks carry `cache_control: ephemeral`. Identical system prompts across calls hit the prefix cache. Cache effectiveness logged in observability output (`cache_read_input_tokens`).
- **No user input is interpolated into prompts.** Fields are Pydantic-typed slots; the symbol comes from the URL path (validated), tool outputs are structured (validated). See [docs/security.md](docs/security.md) A03.

## Anti-hallucination disciplines

Non-negotiable. Every Phase 2 PR is gated on these.

1. **Citation discipline.** [`app/schemas/research.py`](app/schemas/research.py) makes citations the *only* path. `Source` is frozen (`tool, fetched_at, url, detail`); `Claim` carries `value + source`; `Section` has `claims: list[Claim] + summary: str`. Free-form text exists only inside `summary`, and the eval rubric checks every number in `summary` is also in `claims`.
2. **Per-section confidence** (`high|medium|low`), set programmatically by the agent based on data freshness + sparsity. Never set by the LLM directly.
3. **Eval harness.** [`tests/evals/`](tests/evals/) runs rubric unit tests on every PR (free, no LLM). Real-LLM golden tests in `test_golden.py` skip without `ANTHROPIC_API_KEY` so they don't run on every PR; can be triggered locally or on a separate cost-aware CI lane.
4. **`last_updated` per data point.** Every `Claim.source.fetched_at` is the wall time the upstream call returned, not when the report was generated. `Section.last_updated` is the max across its claims.

## API surface

| Group | Routes | Status |
|---|---|---|
| Health | `GET /v1/health` | ✅ |
| Symbols | `GET /v1/symbols`, `POST /v1/symbols` | ✅ |
| News | `GET /v1/news`, `GET /v1/news/{id}`, `POST /v1/news/ingest` | ✅ |
| Market | `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history`, `POST /v1/market/{symbol}/ingest` | ✅ |
| Research | `POST /v1/research/{symbol}?focus={full,earnings}&refresh={false,true}` | ✅ (PRs #26 + #28 + #29) — same-day cache + per-IP rate limit |
| Analysis / Reports / Forecasts | legacy v1 placeholders | return 501 — to be removed or redirected to `/v1/research` |

Errors are RFC 7807 problem+json via [`app/core/errors.py`](app/core/errors.py).

## Cost model

| Item | Monthly | Notes |
|---|---|---|
| Fly.io shared-CPU 256MB | $0–5 | Auto-stop machines; idle cost $0 |
| Neon free tier | $0 | 0.5 GB storage, autosuspend |
| Anthropic API | $1–10 | Cost-tier routed; cached system prompts. Scales with research-report volume. |
| NewsAPI dev tier | $0 | 100 req/day. Yahoo RSS fills the gap. |
| **Estimated total** | **$5–15** | Well inside the $50–80 design budget |

Hard rate limit on `/v1/research/*` shipped in PR #29 + the post-cache refinement: in-memory per-IP token bucket (default 3/hour, env-tunable). Runs *after* the cache lookup so cache hits are free — only synthesis-bound requests consume tokens. Bounds LLM cost without 429ing legitimate re-reads of already-generated reports. See README §"Rate limit posture" for the trade-off.

## Security

Active mitigations for OWASP Top 10 in [docs/security.md](docs/security.md). The two non-negotiables:

- **A09 observability.** Every external call (LLM, market, news, FRED, EDGAR) logged with service id, input/output shape, latency, timestamp, outcome via `log_external_call`.
- **A03 injection.** No user input in SQL strings (SQLAlchemy 2.0 typed `select()`). No user input in LLM prompts (typed Pydantic slots only).

Auth, real rate limiting, and per-user cost caps land only when the project has real users — not a Phase 2 concern.

## Roadmap

**Phase 1 — Core infrastructure (done).** FastAPI scaffold, async DB stack, Alembic, yfinance ingest, RSI + SMA technicals, observability, RFC 7807, deploy to Fly + Neon, CI with Gitleaks + Claude PR review.

**Phase 2 — Equity research assistant (done).**

- 2.0 Foundations ✅ — research schemas, LLM client with cost-tier routing, eval harness with rubric (structure + factuality + latency).
- 2.1 Tool registry ✅ — 9/9 active tools shipped (point-in-time; histories extend in Phase 3).
- 2.2 Agent + `POST /v1/research/{symbol}` ✅ — deterministic-everything-except-prose architecture (PR #26); same-day cache (PR #28); per-IP rate limit (PR #29 + post-cache refinement). Real-LLM golden eval at factuality 0.97.

**Phase 3.0 — Frontend backend prereqs (done, PR #31).** Shared-secret bearer auth dep (`/v1/research/*`), CORS middleware (single-origin allowlist via `FRONTEND_ORIGIN`), `GET /v1/research` paginated list endpoint for the dashboard sidebar. 30 new tests; full suite at 426 passing.

**Phase 3.1 — Frontend MVP (done, PR #32; deploy held).** React + Vite + TS + Tailwind + TanStack Query + Zod. Login screen, dashboard, report renderer, past-reports sidebar. 19 vitest tests; production build 75 KB gzipped. Vercel deploy held until Phase 3 visual-depth work ships per ADR 0004 — shipping the dashboard against today's text-only report would just need an immediate upgrade.

**Phase 3 — Visual-first depth (active).** Per [ADR 0004](docs/adr/0004-visual-first-product-shape.md):

- 3.1 Schema — `Claim.history?: list[ClaimHistoryPoint]` (period + value), backwards-compatible.
- 3.2 Tool extensions — `fetch_fundamentals`, `fetch_earnings`, `fetch_macro` learn to populate history from yfinance's quarterly tables, FRED series, and earnings-date history. New derived `fetch_valuation_history` for rolling P/E / P/S / EV/EBITDA over time.
- 3.3 Frontend visualization — Recharts. `Sparkline` inline next to history-bearing claims, `SectionChart` for top-level visualizations (price+SMA, fundamentals trend, macro series), `PeerScatter` for the Peers section.
- 3.4 Eval rubric extension — `_matches_claim` reads `claim.history[*].value` so prose like "EPS rose from 1.46 to 2.18" passes when both numbers are in the referenced claim's history.
- 3.5 Frontend deploy — Vercel + Fly secrets + dogfood + docs sweep.

**Phase 4 — Narrative layer (deferred until Phase 3 ships).** Per ADR 0004: explicit Bulls Say / Bears Say with `claim_refs` enforcement, a What Changed delta section (mechanical from Phase 3 history), catalyst awareness wiring `fetch_news` into reports, new `?focus=thesis` mode. Lands only after Phase 3 dogfooding confirms the data foundation is right; without Phase 3 first, Phase 4 is just longer-winded versions of today's summaries.

**Indefinitely deferred (future scope).** `search_history` (pgvector RAG over stored news + filings), `compute_options` (yfinance options + daily IV snapshot), Reddit sentiment, real auth + per-user cost caps + Redis-backed horizontal rate limit. None of these address the perceived-shallowness gap that motivated the Phase 3/4 reshuffle; revisit when there's a concrete trigger.

## Risks

| Risk | Mitigation |
|---|---|
| EDGAR / transcript scrapers break | Tools fail gracefully; agent surfaces "data unavailable" rather than fabricating. |
| LLM cost overruns | Cost-tier routing, prompt caching, per-symbol response cache, hard rate limit before public exposure. |
| Free-data sparsity | Per-section confidence + `last_updated`; eval harness catches regressions in factuality. |
| yfinance schema drift | Defensive lookups (`_safe_loc`); missing fields become None claims with a stable shape. |
| Eval coverage gaps | Add golden cases as tools land; rubric scores both structure and factuality. |

## ADR index

- [ADR 0001](docs/adr/0001-stack-choice.md) — FastAPI + async SQLAlchemy + PostgreSQL
- [ADR 0002](docs/adr/0002-deployment.md) — Fly.io + Neon
- [ADR 0003](docs/adr/0003-pivot-equity-research.md) — Pivot to AI Equity Research Assistant

## Resume framing

What this project demonstrates, with backing in the codebase:

| Skill | Backed by |
|---|---|
| Production system design | Live deploy, RFC 7807 errors, observability, CI, migrations, deploy pipeline |
| Modern AI patterns (2026) | Single agent + tools, structured outputs, eval harness, cost-tier routing, prompt caching |
| Anti-hallucination engineering | Citation-enforcing schema, per-section confidence, factuality rubric, `last_updated` invariant |
| Cost-aware engineering | Free-tier infra + free data + Haiku triage / Sonnet synth split, ~$5–15/mo all-in |
| Test discipline | TDD on services + agents, mocked providers, separate eval harness, 80%+ coverage on `app/services/` |
| Tradeoff articulation | ADRs 0001–0003 capture the *why* behind every load-bearing choice |
