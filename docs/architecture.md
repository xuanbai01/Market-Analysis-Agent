# Architecture

Read this before opening source files. The [design_doc.md](../design_doc.md) at the repo root is the long-form system design; this page is the short version of what actually exists in code today and where it's heading.

## Project Overview

The **AI Equity Research Assistant** — a FastAPI backend that exposes one primary endpoint (`POST /v1/research/{symbol}`) returning a Pydantic-typed citation-backed structured research report, plus a React + Vite + TypeScript frontend that renders it. Single agent + well-designed tools, free data only, citation discipline non-negotiable. Visual-first, delta-driven product shape per [ADR 0004](adr/0004-visual-first-product-shape.md).

The original v1 vision (real-time multi-agent platform with scheduled news firehose, Discord bot, Pinecone vector store, Polygon paid feed) was [explicitly cut](adr/0003-pivot-equity-research.md) in favour of depth-over-freshness on free data.

Real operating cost: ~$0–5/mo (Fly auto-stop + Neon free tier + per-call LLM billing under cost-tier routing; under a cent per fresh report on DeepSeek Flash).

## Tech Stack

| Layer | Technology | Status |
|---|---|---|
| Language | Python 3.11 (backend), TypeScript 5.6 (frontend) | ✅ |
| Backend framework | FastAPI 0.115 | ✅ |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | ✅ |
| Config | pydantic-settings | ✅ |
| Database | PostgreSQL 15 (Docker locally; Neon free tier in prod) | ✅ |
| Schema migrations | Alembic 1.13 (async mode) | ✅ |
| LLM | Switchable via `LLM_PROVIDER` ([ADR 0006](adr/0006-pluggable-llm-provider.md)): Anthropic — Claude Haiku 4.5 (triage: risk + news categorizers) + Sonnet 4.6 (synth), the default; or DeepSeek V4.1 Flash (`deepseek-flash`) for both tiers. Per-tier override via `LLM_TRIAGE_MODEL` / `LLM_SYNTH_MODEL` | ✅ |
| Market data | yfinance | ✅ |
| News | NewsAPI free tier + Yahoo per-ticker RSS | ✅ |
| Filings | SEC EDGAR (with disk cache + polite-crawl) | ✅ |
| Macro | FRED API | ✅ |
| Hosting | Fly.io (auto-stop machines) + Neon (Postgres) + Vercel (frontend) | ✅ API https://market-analysis-agent.fly.dev, dashboard https://market-analysis-agent-red.vercel.app |
| Frontend stack | Vite + React 18 + Tailwind + TanStack Query + Zod | ✅ |
| Tests | pytest + pytest-asyncio (backend), vitest + happy-dom (frontend) | ✅ counts in [testing.md](testing.md) |
| Lint | ruff (backend), ESLint (frontend) | ✅ |
| CI | GitHub Actions (tests + Gitleaks + Claude PR review) + push-to-deploy | ✅ |

**Indefinitely deferred per [ADR 0004](adr/0004-visual-first-product-shape.md):** pgvector (`search_history`), yfinance options chain (`compute_options`), Redis (no horizontal-scale rate limit need yet), Celery (no scheduled work).

## Repository Structure

```
/
├── app/                         # FastAPI application
│   ├── main.py                  # App factory, router mounting, CORS, error handlers
│   ├── core/                    # settings, auth, cors, errors, observability
│   ├── api/v1/
│   │   ├── dependencies.py      # DB session, rate limit
│   │   └── routers/             # health, symbols, news, market, research (the v2 surface)
│   ├── db/
│   │   ├── session.py           # async engine + sessionmaker
│   │   └── models/              # Symbol, NewsItemModel, NewsSymbol, Candle, ResearchReportRow
│   ├── schemas/                 # Pydantic request/response (research.py is the v2 schema)
│   └── services/                # tools (fetch_*, parse_*), orchestrator, cache, rate_limit, llm
├── alembic/versions/            # 0001 baseline, 0002 news_symbols, 0003 research_reports
├── frontend/                    # Vite + React 18 + TS dashboard (Phase 4)
│   ├── src/
│   │   ├── App.tsx              # Router + auth guard. SymbolDetailPage + ComparePage lazy.
│   │   ├── components/
│   │   │   ├── AppShell.tsx     # Sidebar + main outlet + global ⌘K listener
│   │   │   ├── SidebarShell.tsx # Search/Home/Compare + live Watchlist & Recent; collapses to a 64px rail
│   │   │   ├── MarketStrip.tsx  # markets row above every page + fear & greed (est.) breakdown
│   │   │   ├── LandingPage.tsx  # / route — search + past reports
│   │   │   ├── SymbolDetailPage.tsx  # /symbol/:ticker (LAZY chunk)
│   │   │   ├── compare/         # /compare/?a&b sub-tree (LAZY chunk)
│   │   │   ├── lens/            # /lens, /lens/:id (LAZY chunks)
│   │   │   ├── search/          # SearchModal (LAZY chunk)
│   │   │   └── ...              # Strata cards: HeroCard, AnalystViewCard, QualityCard,
│   │   │                        #   EarningsCard, ValuationCard, PerShareGrowthCard,
│   │   │                        #   CashAndCapitalCard, CapitalReturnsCard, RiskDiffCard,
│   │   │                        #   MacroPanel, BusinessCard, NewsList, ContextBand,
│   │   │                        #   SectionNav, ReportFreshness, ErrorBoundary,
│   │   │                        #   HeaderPills, NarrativeStrip, WatchlistButton + SVG primitives
│   │   └── lib/                 # Zod schemas, API client, auth helpers, format helpers,
│   │                            #   per-card extractors, watchlist + recent localStorage,
│   │                            #   popular-tickers
│   └── vercel.json              # Vercel deploy config (SPA rewrites; builds on push to main)
├── tests/                       # pytest-asyncio; per-test SAVEPOINT rollback. Plus tests/evals/ (rubric + golden)
├── docs/                        # this directory (architecture, security, testing, commands, ADRs)
├── tasks/                       # active sprint (todo.md) + lessons learned
├── scripts/                     # smoke.py — exercises each tool against live providers
├── design_doc.md                # long-form system design (read first)
├── fly.toml
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Layering Rule

Route handler → Service (or repository) → Model/DB. Never put business logic in a route. Never return an ORM object directly from a route; pass through a Pydantic response schema.

```
FastAPI router  ─▶  services/<domain>_<role>.py
                         │
                         ▶  db/models/<domain>.py  (SQLAlchemy)
                         ▶  external providers (yfinance, EDGAR, FRED, Anthropic / DeepSeek)
```

For the v2 research endpoint specifically:

```
POST /v1/research/{symbol}
  └▶ research_cache.lookup_recent       (free; pre-rate-limit; a report older than
                                          REPORT_VERSION is rebuilt, or served if the rebuild can't run)
  └▶ enforce_research_rate_limit         (only on cache miss)
  └▶ research_orchestrator.compose_research_report
       ├▶ tool fan-out (asyncio.gather, return_exceptions=True)
       │    fetch_fundamentals / fetch_earnings / fetch_peers /
       │    fetch_macro / extract_10k_business / extract_10k_risks_diff /
       │    fetch_annual_history (SEC XBRL, ten years per share + year-end multiples) /
       │    fetch_insider_activity (Form 4s, last six months)
       ├▶ deterministic claim builders   (per-section, code picks claims, not LLM)
       ├▶ llm.synth_call                 (Sonnet writes summary prose under forced schema)
       ├▶ research_thesis.compose_thesis (in parallel: the analyst view, claim-id citations)
       └▶ research_confidence.score_section  (programmatic, not LLM-set)
  └▶ research_cache.upsert
```

## Data Model (current)

| Entity | Fields | Notes |
|---|---|---|
| `symbols` | `symbol` (PK, varchar 16), `name` (varchar 128, nullable) | Seeded with NVDA, SPY. |
| `news_items` | `id` (PK, varchar 64), `ts` (timestamptz), `title`, `url`, `source` | Indexed on `ts DESC`. |
| `news_symbols` | composite PK `(news_id, symbol)` | Join table for symbol-tagged news. Cascading FKs both directions. |
| `candles` | composite PK `(symbol, ts, interval)`; OHLCV + volume | FK → `symbols`. Indexed `(symbol, interval, ts DESC)`. Append-only. |
| `research_reports` | composite PK `(symbol, focus, report_date)`; `report_json` (JSONB), `generated_at` (timestamptz) | Same-day cache. JSONB stores serialized `ResearchReport`. Lookup is time-windowed via `generated_at` (configurable via `RESEARCH_CACHE_MAX_AGE_HOURS`). |

## Backend routes (current)

| Group | Routes | Status |
|---|---|---|
| Health | `GET /v1/health` | ✅ real (pings DB) |
| Symbols | `GET /v1/symbols`, `POST /v1/symbols` | ✅ real. Auth-gated. |
| News | `POST /v1/news/ingest`, `GET /v1/news`, `GET /v1/news/{id}` | ✅ real (NewsAPI + Yahoo RSS, symbol-tagged). Auth-gated (`POST` spends NewsAPI quota; the reads show which tickers are tracked). |
| Market | `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ real (yfinance ingest + upsert + technicals). Auth-gated. |
| **Research** | **`POST /v1/research/{symbol}?focus={full,earnings}&refresh={false,true}`** | ✅ **the v2 primary endpoint.** Auth-gated when `BACKEND_SHARED_SECRET` is set. Per-IP rate limit. |
| Research list | `GET /v1/research?limit=20&offset=0&symbol=...` | ✅ paginated `ResearchReportSummary[]` for the dashboard sidebar |
| Phase 4 — prices | `GET /v1/market/:ticker/prices?range={60D\|1Y\|5Y}` | ✅ Phase 4.1 — read-through `candles` cache, falls through to yfinance ingest on miss. Auth-gated. |
| Market strip | `GET /v1/market/overview` | ✅ 2026-11 — headline quotes (S&P 500, Nasdaq 100, Dow, VIX, Russell 2000, US 10Y, dollar, gold, WTI, bitcoin) + our fear & greed estimate (`market_sentiment.py`: momentum, VIX, safe-haven and junk-bond demand, each ranked against its past year). yfinance, in-memory cache (5 min quotes / 1 h sentiment), serves stale on provider failure. Auth-gated. |
| Demo | `GET /v1/demo`, `GET /v1/demo/research/{symbol}`, `GET /v1/demo/market/{symbol}/prices` | ✅ 2026-11 — public and read-only: the latest stored report and stored prices for the tickers in `DEMO_SYMBOLS`. Never generates or fetches; responses cached 5 min as bytes; per-IP limit. **Not auth-gated, by design** (security.md A01). |
| Lenses | `GET /v1/lens`, `GET /v1/lens/{id}` | ✅ 2026-11 (ADR 0007 layer 3) — cross-company lens built from SEC XBRL annual filings (`xbrl.py`: tag merging per year, SEC calendar frames, 24 h disk cache) and `lens.py` (10-year window ending at the latest year every company filed; per-year distribution stats; computed facts; cited AI narrative). First lens: megacap tech capex. In-memory cache 24 h, stale on failure, 503 when nothing cached. Auth-gated. |

## Frontend routes (current)

Lazy-loading is the binding bundle constraint — the main chunk must stay under 100 KB gzipped (current sizes: [frontend/README.md](../frontend/README.md)). Every authenticated route except `/` is split into its own chunk so the entry stays lean.

| Route | State | Chunk |
|---|---|---|
| `/login` | ✅ Pre-auth screen. Links to the demo when there is one. | main |
| `/demo`, `/demo/:ticker` | ✅ Public read-only demo, no sign-in: an index of the demo tickers and the same dashboard, read through `/v1/demo`. No sidebar, search, market strip, Regenerate or watchlist. | **lazy** (shell + index; the dashboard chunk is shared) |
| `/` | ✅ LandingPage — search bar + Past Reports (Watchlist and Recent live in the sidebar on every page). | main |
| `/symbol/:ticker` | ✅ The dashboard: sticky section nav, HeroCard, AnalystViewCard, full-width Quality / Earnings / Valuation / Per-share growth, an equal-height row of Cash & capital · Capital returns · Risk · Macro (only the cards with data), Insider activity, Business + News. | **lazy** |
| `/compare?a=X&b=Y` | ✅ Phase 4.6.A — two-ticker side-by-side. One % change price chart, growth by metric, risk on one scale. | **lazy** |
| `/lens`, `/lens/:id` | ✅ ADR 0007 layer 3 — cross-company lenses: the yearly distribution of a metric across a group (DistributionChart), dollars by company (CapexBars), a latest-year table and a cited AI read. | **lazy** |
| (overlay) `SearchModal` | ✅ Phase 4.7 — ⌘K-triggered. | **lazy** |

Errors are serialized as [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](../app/core/errors.py). The handler propagates `HTTPException.headers` so `Retry-After` (429) and `WWW-Authenticate` (401) survive the wrap.

## External Integrations (current)

| Service | Purpose | Failure mode |
|---|---|---|
| yfinance | OHLCV, fundamentals, peers, earnings, ten years of closes for the year-end multiples | Defensive `_safe_loc` lookups; missing fields become `None`-valued claims with stable shape |
| SEC EDGAR | Filings (10-K, Form 4, 13F-HR); XBRL company concepts for lenses and the ten-year per-share history | Disk-cached: filing texts forever (filings never change), the list of filings 12 h, XBRL 24 h. SEC `User-Agent` mandatory; every request in the process spaced through one lock (8 a second, under SEC's 10). A company that moved to a new registrant is read across both (`sec_registrants.py`). A ticker SEC doesn't know fails the SEC tools only; their cards drop out and the page says so |
| NewsAPI | News articles | Optional — skipped silently when `NEWSAPI_KEY` empty |
| FRED | Macro series | Optional — `fetch_macro` emits metadata claims with None values when `FRED_API_KEY` empty |
| Anthropic Claude | Synth (Sonnet 4.6) + triage (Haiku 4.5) when `LLM_PROVIDER=anthropic` (default) | `RuntimeError` → 503 problem+json (key not configured / provider API error) |
| DeepSeek | Synth + triage (`deepseek-flash`, thinking disabled) when `LLM_PROVIDER=deepseek`. OpenAI-format API via the `openai` SDK (`app/services/llm_deepseek.py`) | `RuntimeError` → 503 problem+json (key not configured / provider API error, e.g. 402 out of credit) |

Every external call is logged via `log_external_call` (service id, input/output summary, latency ms, timestamp, outcome). See [security.md §A09](security.md#a09) for why.

## Architecture Decisions

ADRs in [docs/adr/](adr/):

- [0001](adr/0001-stack-choice.md) — FastAPI + async SQLAlchemy over Flask/Django.
- [0002](adr/0002-deployment.md) — Deploy to Fly.io + Postgres on Neon.
- [0003](adr/0003-pivot-equity-research.md) — Pivot from v1 (real-time multi-agent platform) to v2 (AI Equity Research Assistant).
- [0004](adr/0004-visual-first-product-shape.md) — Visual-first, delta-driven; not chasing Morningstar-narrative depth.
- [0005](adr/0005-symbol-centric-dashboard.md) — **Read this before proposing surface-shape changes.** Pivot from "click Generate → static report" to symbol-centric dashboard with adaptive layouts (Phase 4).
- [0006](adr/0006-pluggable-llm-provider.md) — LLM provider switchable per `LLM_PROVIDER` (Anthropic default, DeepSeek Flash).
- [0007](adr/0007-analytical-narratives.md) — Card prose interprets: derived comparison claims (`research_derived.py`), history in the prompt, sector-aware framing; citation rule unchanged.
