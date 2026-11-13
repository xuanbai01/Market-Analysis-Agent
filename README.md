# Market Analysis Agent

An **AI Equity Research Assistant**. Open a ticker and get a research dashboard: price, quality, earnings, valuation against peers, per-share growth, cash and capital returns, the year-over-year change in 10-K risk factors, macro context, business and news, plus an **analyst view** (headline, bull case, bear case, what changed, what to watch). Every number on the page, and every number the AI writes, cites the data it came from. Free data only, on ~$5/mo of infrastructure.

- **Demo, no sign-in:** <https://market-analysis-agent-red.vercel.app/demo> (a few pre-built reports, read-only)
- **Dashboard:** <https://market-analysis-agent-red.vercel.app> (sign-in with the shared secret; any ticker)
- **API:** <https://market-analysis-agent.fly.dev/docs>

> **Status — Phases 1–5 done (2026-11).** The symbol-centric dashboard ([ADR 0005](docs/adr/0005-symbol-centric-dashboard.md)) is deployed: React on Vercel, FastAPI on Fly, Postgres on Neon, DeepSeek V4.1 Flash for the prose ([ADR 0006](docs/adr/0006-pluggable-llm-provider.md)). The Phase 4.8 dogfood gate sent the project into the narrative layer: card prose that interprets instead of listing, a cited analyst view, and cross-company lenses built from SEC XBRL ([ADR 0007](docs/adr/0007-analytical-narratives.md)). Live golden eval: factuality 1.000 on all five golden tickers. Test counts are in [docs/testing.md](docs/testing.md), bundle sizes in [frontend/README.md](frontend/README.md), the open plan in [tasks/todo.md](tasks/todo.md) and the history in [docs/changelog.md](docs/changelog.md).

## What this is (and isn't)

| | |
|---|---|
| **Is** | A FastAPI backend whose primary endpoint, `POST /v1/research/{symbol}`, returns a Pydantic-typed research report, and a React + Vite dashboard at `/symbol/:ticker` that renders it. Single agent + well-designed tools; code picks the claims and computes every comparison, the LLM only writes prose under a forced schema. |
| **Is** | Built on **free data only** — yfinance, SEC EDGAR (filings + XBRL), NewsAPI free tier + Yahoo RSS, FRED — and free-tier infrastructure (Fly.io, Neon, Vercel). Real cost: ~$0–5/mo; a fresh report costs about a cent of LLM on DeepSeek Flash. |
| **Is** | **Visual-first, delta-driven** per [ADR 0004](docs/adr/0004-visual-first-product-shape.md): history drawn as charts, prose short and interpretive. Layouts adapt to distressed names (cash runway and risk lift above valuation). |
| **Isn't** | A real-time market platform. The original v1 vision (15-min news firehose, Discord bot, multi-agent-as-architecture) was [explicitly cut](docs/adr/0003-pivot-equity-research.md) in favour of depth over freshness. |
| **Isn't** | A Morningstar-shaped analyst note. No DCF, fair-value estimates or letter grades (ADR 0004). The analyst view argues from the report's own numbers; it never computes a number or brings in outside facts. |
| **Isn't** | A trading signal generator. Research synthesis, not buy/sell recommendations. Every claim cites its source so a human can verify before acting. |

## The dashboard

| Route | What it shows |
|---|---|
| `/symbol/:ticker` | Sticky section nav; **Hero** (price chart with axes + hover, featured stats; distress pills and a metric swap for unprofitable names); **Analyst view** (headline, then bull / bear and what changed / what to watch as one line each: a short title and its key figure, opening to the full reasoning and the claims behind it, each jumping to its card); full-width **Quality**, **Earnings** (20Q EPS bars, beat rate, recent prints), **Valuation** (multiples vs peer median + peer scatter, and P/E, P/S and P/FCF against the company's own fiscal year-ends), **Per-share growth**; one equal-height row of **Cash & capital**, **Capital returns**, **10-K risk diff** and **Macro** (only the cards with data); **Business** + **News**. "Generated 2 days ago · Regenerate" replaces a stale cached report. |
| `/compare?a=X&b=Y` | Two tickers side by side: hero, valuation and quality rows, operating-margin and per-share growth overlays, risk diffs. |
| `/lens/:id` | One metric across a group of companies over 10 years from SEC XBRL, with a cited AI read. First lens: **megacap tech capex** (AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA) — capex intensity distribution by year, capex dollars by company, capex ÷ operating cash flow. |
| `/` | Search + past reports. The sidebar (Search ⌘K · Home · Compare · Lenses · Watchlist · Recent) and a **market strip** (S&P 500, Nasdaq 100, Dow, VIX, our fear & greed estimate, Russell 2000, 10Y, dollar, gold, WTI, bitcoin) sit on every page. |

## Quickstart

```bash
# 1. Clone
git clone https://github.com/xuanbai01/Market-Analysis-Agent.git
cd Market-Analysis-Agent

# 2. Environment
cp .env.example .env              # dev defaults, no real secrets required

# 3. Database
docker compose up -d db            # Postgres 15 on :5432 (+ test_db)

# 4. Install + migrate + run the API
uv sync                            # pinned deps (Python 3.11 via .python-version)
uv run alembic upgrade head        # schema + seed rows
uv run uvicorn app.main:app --reload

# 5. Dashboard (second terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Verify with `curl http://localhost:8000/v1/health` → `{"status":"ok","db":true}` and the Swagger UI at <http://localhost:8000/docs>. Reports need one LLM key in `.env`: `ANTHROPIC_API_KEY` (default `LLM_PROVIDER=anthropic`) or `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY`. `FRED_API_KEY` and `NEWSAPI_KEY` are optional; those sections degrade without them.

[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) covers the frontend, both test suites and troubleshooting (Windows port clashes, stale `.env`, and the other setup problems this project has hit).

## API

| Endpoint | State |
|---|---|
| `POST /v1/research/{symbol}?focus={full,earnings}&refresh={false,true}` | ✅ **The primary endpoint.** 9 sections in `full` (Business, News, Valuation, Quality, Capital Allocation, Earnings, Peers, Risk Factors, Macro) plus the analyst view; 4 in `earnings`. Cached up to 7 days; per-IP rate limit on fresh reports. |
| `GET /v1/research?limit=20&offset=0&symbol=...` | ✅ Paginated report summaries for the past-reports list. |
| `GET /v1/market/{symbol}/prices?range={60D\|1Y\|5Y}` | ✅ OHLCV from the `candles` cache, falling through to a yfinance ingest on a miss. |
| `GET /v1/market/overview` | ✅ The market strip: headline quotes + our fear & greed estimate. In-memory cache, serves stale on provider failure. |
| `GET /v1/lens`, `GET /v1/lens/{id}` | ✅ Cross-company lenses from SEC XBRL. |
| `GET /v1/demo`, `/v1/demo/research/{symbol}`, `/v1/demo/market/{symbol}/prices` | ✅ Public, read-only: stored reports and prices for the tickers in `DEMO_SYMBOLS`. Never generates anything. |
| `GET /v1/health` | ✅ Pings the DB. |
| `GET/POST /v1/symbols`, `GET /v1/news`, `GET /v1/news/{id}`, `POST /v1/news/ingest`, `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ Phase 1 data routes. |

With `BACKEND_SHARED_SECRET` set (production), research, prices, overview, lenses and every write or quota-spending route require `Authorization: Bearer <secret>`; CORS allows only `FRONTEND_ORIGIN`. Errors are [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](app/core/errors.py).

```bash
# Cold call: ~20–90 s (tool fan-out + two LLM calls; uncached 10-K filings take longest)
curl -X POST http://localhost:8000/v1/research/AAPL -o report.json

# Same call within 7 days: served from research_reports, no LLM call
curl -X POST http://localhost:8000/v1/research/AAPL -o report-cached.json

# Force a fresh report (consumes a rate-limit token)
curl -X POST "http://localhost:8000/v1/research/AAPL?refresh=true" -o report-fresh.json
```

`uv run python scripts/smoke.py AAPL --skip-13f` runs each data tool against the live providers without the LLM — a fast check that nothing drifted upstream.

## How a report is built

```
POST /v1/research/{symbol}?focus=full
        │
        ▼
   Cache lookup (research_reports, default 7 days) ── hit ──▶ return (no LLM, no token)
        │ miss
        ▼
   Rate limit (per-IP token bucket; default 3/h, 30/h in production)
        │
        ▼
   Orchestrator — deterministic everything except prose
   ─ data tools in parallel (fundamentals, earnings, peers, macro,
     10-K business + risk diff, business info, news)
   ─ static SECTION_TO_CLAIM_KEYS: code picks the claims, not the LLM
   ─ derived comparison claims computed in code (YoY margins, TTM FCF
     yield, payout + coverage, premium to peer median, beat streak …)
   ─ two LLM calls in parallel, both under forced schemas:
       section prose (summary + one-line card narrative per section)
       analyst view (bull / bear / changed / watch, cites claim ids)
   ─ citations checked in code: unknown ids and points whose quoted
     numbers match none of their cited claims are dropped
   ─ confidence + layout signals (unprofitable, cash runway …) computed
        │
        ▼
   Cache upsert ──▶ ResearchReport { sections[claims, summary, card_narrative,
                                    confidence], thesis, layout_signals, … }
```

**Data tools** — each is a focused async function, every external call logged via `log_external_call`:

| Tool | Source |
|---|---|
| `fetch_fundamentals` | yfinance info + quarterly statements (16 history-bearing claims) |
| `fetch_earnings` | yfinance earnings dates: 20 quarters of EPS, consensus, beat rate |
| `fetch_peers` | curated sector map + yfinance fallback, peer matrix + medians |
| `fetch_macro` | FRED, sector → series map, ~36 monthly points per series |
| `extract_10k_business`, `extract_10k_risks_diff` | SEC EDGAR 10-K (disk cache, polite crawl); risk paragraphs categorized by the triage model |
| `fetch_business_info` | yfinance business summary, HQ, employees |
| `fetch_news` | Yahoo per-ticker RSS (+ NewsAPI when keyed), ingested per report, categorized by the triage model |
| `xbrl` (lenses) | SEC company-concept API, tags merged year by year, calendar frames |
| Form 4 / 13F parsers, technicals | parsers and RSI/SMA from Phase 2, not on the dashboard today |

**LLM:** `LLM_PROVIDER` picks the backend at call time ([ADR 0006](docs/adr/0006-pluggable-llm-provider.md)): Anthropic (Haiku 4.5 triage + Sonnet 4.6 synthesis; the code default) or DeepSeek V4.1 Flash for both tiers (production). Triage runs the risk and news categorizers; synthesis writes the section prose, the analyst view and the lens read.

### Anti-hallucination disciplines

A research agent that produces well-formatted hallucinations is worse than none. Every PR is held to:

1. **Citation discipline** — every claim cites the tool call that produced it; the schema leaves no other path. Analyst-view and lens points cite claim ids, checked in code.
2. **The model never computes a number** — comparisons are derived claims computed in code; the prompt forbids arithmetic and outside facts.
3. **Per-section confidence** (`high | medium | low`) set programmatically from freshness and sparsity, never by the LLM.
4. **Eval harness** — the factuality rubric checks every number in the summaries, card narratives and analyst view against the claims (including their history). Rubric unit tests run on every PR; the live golden eval (AAPL, NVDA, RIVN, JPM, KO, XOM) is opt-in with `uv run pytest -m live_llm tests/evals -s`.
5. **`fetched_at` per data point** so stale data never passes as fresh.

### Rate limit posture

The rate limit on `/v1/research/{symbol}` runs **after** the cache lookup: cache hits are free, only fresh reports consume tokens, because the limit exists to bound LLM cost. The code default is 3 fresh reports per IP per hour; production runs 30/h during dogfooding (`RESEARCH_RATE_LIMIT_PER_HOUR` in `fly.toml`) and should drop before the URL is shared. To make every request consume a token, move `enforce_research_rate_limit` into the route decorator's `dependencies` in [`app/api/v1/routers/research.py`](app/api/v1/routers/research.py) and invert `test_cache_hits_do_not_consume_rate_limit_tokens` / `test_rate_limit_runs_after_cache_miss_only`.

## Repository layout

```
/
├── app/                         # FastAPI application
│   ├── main.py                  # app factory, CORS, error handlers, router mounting
│   ├── core/                    # settings, auth (shared secret), cors, errors, observability
│   ├── api/v1/routers/          # health, symbols, news, market, research, lens
│   ├── db/models/               # Symbol, NewsItemModel, NewsSymbol, Candle, ResearchReportRow
│   ├── schemas/                 # Pydantic request/response (research.py is the report schema)
│   └── services/                # data tools, orchestrator, derived claims, thesis, layout
│                                # signals, cache, rate limit, LLM adapters, xbrl + lens,
│                                # market overview + sentiment
├── alembic/versions/            # 0001 baseline, 0002 news_symbols, 0003 research_reports
├── frontend/                    # Vite + React 18 + TS dashboard (see frontend/README.md)
│   └── src/
│       ├── components/          # AppShell, SidebarShell, MarketStrip, SymbolDetailPage (lazy)
│       │                        # and its cards; compare/, lens/, search/ (each lazy)
│       └── lib/                 # Zod schemas, API client, per-card extractors, formatters,
│                                # watchlist / recent storage
├── tests/                       # pytest-asyncio, per-test SAVEPOINT rollback; tests/evals/
├── docs/                        # architecture, deployment, security, testing, commands, ADRs 0001–0007
├── tasks/                       # todo.md, lessons.md, dogfood logs
├── scripts/smoke.py             # every data tool against live providers
├── design_doc.md                # long-form system design
├── fly.toml · Dockerfile · docker-compose.yml · pyproject.toml
```

## Development

| Task | Command |
|---|---|
| API dev server | `uv run uvicorn app.main:app --reload` |
| Dashboard dev server | `cd frontend && npm run dev` |
| Backend tests | `uv run pytest -v` (needs Postgres at `DATABASE_URL`) |
| Frontend tests | `cd frontend && npm run test` |
| Lint | `uv run ruff check app tests` · `cd frontend && npm run lint && npm run typecheck` |
| Migrations | `uv run alembic upgrade head` |

More in [docs/commands.md](docs/commands.md).

## CI and deployment

Every PR runs ([.github/workflows/ci.yml](.github/workflows/ci.yml)): backend `ruff` + `pytest` against a Postgres service; frontend lint, typecheck, vitest and build; a production-image job that builds the Dockerfile and boots it against Postgres (`alembic upgrade` + `/v1/health`); Gitleaks; and an AI PR review.

A push to `main` deploys both halves: [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs `flyctl deploy` (the container applies migrations before `uvicorn` starts) and Vercel builds `frontend/`. Setup, secrets and operations are in [docs/deployment.md](docs/deployment.md); rationale in [ADR 0002](docs/adr/0002-deployment.md).

## Roadmap

- **Phase 1 — Core infrastructure** ✅ FastAPI, Alembic, tests, yfinance ingest, technicals, Fly + Neon, push-to-deploy.
- **Phase 2 — Research assistant** ✅ Citation-enforcing schema, free-data tools, deterministic orchestrator, cache, rate limit, golden eval.
- **Phase 3 — Visual-first depth** ✅ `Claim.history` on fundamentals, earnings and macro; history-aware rubric.
- **Phase 4 — Symbol-centric dashboard** ✅ ([ADR 0005](docs/adr/0005-symbol-centric-dashboard.md)) Strata design, dedicated cards and SVG charts, adaptive layouts for distressed names, Compare, search / watchlist / recent; 4.8 deployed it and ran the dogfood gate, which also brought readable chart axes, the sidebar rewrite, the market strip, Regenerate, error boundaries and the layout pass.
- **Phase 5 — Narrative layer** ✅ (the 4.8 gate's outcome, [ADR 0007](docs/adr/0007-analytical-narratives.md)) Derived comparison claims and interpretive card prose, the cited analyst view, and the megacap capex lens.
- **Phase 6 — XBRL Tier 2** ⏸ Segment and geography revenue, RPO. Dogfooding hasn't asked for it yet; the XBRL client the lenses use is the starting point.
- **Next** ([tasks/todo.md](tasks/todo.md)) README screenshots, more lenses, insider activity.
- **Indefinitely deferred** ⏸ `search_history` (pgvector RAG), options / IV, Reddit sentiment, real auth + per-user cost caps.

[design_doc.md](design_doc.md) has the system design; the [ADRs](docs/adr/) have the reasoning behind each pivot.

## Contributing

A personal learning / portfolio project, but PRs are welcome:

1. Read [docs/workflow.md](docs/workflow.md) — TDD is non-negotiable for business logic.
2. Read [docs/security.md](docs/security.md) — especially A09 on logging every external call.
3. Open a PR against `main`; the C.L.E.A.R. checklist in [the PR template](.github/pull_request_template.md) is enforced by review.

## License

No license file yet. Treat as all-rights-reserved until one lands.
