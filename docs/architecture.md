# Architecture

Read this before opening source files. The [design_doc.md](../design_doc.md) at the repo root is the long-form system design; this page is the short version of what actually exists in code today and where it's heading.

## Project Overview

The **AI Equity Research Assistant** — a FastAPI backend that exposes one primary endpoint (`POST /v1/research/{symbol}`) returning a Pydantic-typed citation-backed structured research report, plus a React + Vite + TypeScript frontend that renders it. Single agent + well-designed tools, free data only, citation discipline non-negotiable. Visual-first, delta-driven product shape per [ADR 0004](adr/0004-visual-first-product-shape.md).

The original v1 vision (real-time multi-agent platform with scheduled news firehose, Discord bot, Pinecone vector store, Polygon paid feed) was [explicitly cut](adr/0003-pivot-equity-research.md) in favour of depth-over-freshness on free data.

Real operating cost: ~$0–5/mo (Fly auto-stop + Neon free tier + Anthropic per-call billing under cost-tier routing).

## Tech Stack

| Layer | Technology | Status |
|---|---|---|
| Language | Python 3.11 (backend), TypeScript 5.6 (frontend) | ✅ |
| Backend framework | FastAPI 0.115 | ✅ |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | ✅ |
| Config | pydantic-settings | ✅ |
| Database | PostgreSQL 15 (Docker locally; Neon free tier in prod) | ✅ |
| Schema migrations | Alembic 1.13 (async mode) | ✅ |
| LLM | Anthropic — Claude Haiku 4.5 (triage; currently unused) + Claude Sonnet 4.6 (synth) | ✅ |
| Market data | yfinance | ✅ |
| News | NewsAPI free tier + Yahoo per-ticker RSS | ✅ |
| Filings | SEC EDGAR (with disk cache + polite-crawl) | ✅ |
| Macro | FRED API | ✅ |
| Hosting | Fly.io (auto-stop machines) + Neon (Postgres) + Vercel (frontend) | ✅ backend, 🟡 frontend deploy held |
| Frontend stack | Vite + React 18 + Tailwind + TanStack Query + Zod | ✅ |
| Tests | pytest + pytest-asyncio (backend), vitest + happy-dom (frontend) | ✅ 605 backend / 371 frontend |
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
├── frontend/                    # Vite + React dashboard (Phase 3.1)
│   ├── src/
│   │   ├── components/          # LoginScreen, Dashboard, ReportRenderer, etc.
│   │   └── lib/                 # Zod schemas, API client, auth helpers, format helpers
│   └── vercel.json              # Vercel deploy config
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
                         ▶  external providers (yfinance, EDGAR, FRED, Anthropic)
```

For the v2 research endpoint specifically:

```
POST /v1/research/{symbol}
  └▶ research_cache.lookup_recent       (free; pre-rate-limit)
  └▶ enforce_research_rate_limit         (only on cache miss)
  └▶ research_orchestrator.compose_research_report
       ├▶ tool fan-out (asyncio.gather, return_exceptions=True)
       │    fetch_fundamentals / fetch_earnings / fetch_peers /
       │    fetch_macro / extract_10k_business / extract_10k_risks_diff
       ├▶ deterministic claim builders   (per-section, code picks claims, not LLM)
       ├▶ llm.synth_call                 (Sonnet writes summary prose under forced schema)
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

## Routes (current)

| Group | Routes | Status |
|---|---|---|
| Health | `GET /v1/health` | ✅ real (pings DB) |
| Symbols | `GET /v1/symbols`, `POST /v1/symbols` | ✅ real |
| News | `POST /v1/news/ingest`, `GET /v1/news`, `GET /v1/news/{id}` | ✅ real (NewsAPI + Yahoo RSS, symbol-tagged) |
| Market | `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ real (yfinance ingest + upsert + technicals) |
| **Research** | **`POST /v1/research/{symbol}?focus={full,earnings}&refresh={false,true}`** | ✅ **the v2 primary endpoint.** Auth-gated when `BACKEND_SHARED_SECRET` is set. Per-IP rate limit. |
| Research list | `GET /v1/research?limit=20&offset=0&symbol=...` | ✅ paginated `ResearchReportSummary[]` for the dashboard sidebar |
| Phase 4 — prices | `GET /v1/market/:ticker/prices?range={60D\|1Y\|5Y}` | ✅ Phase 4.1 — read-through `candles` cache, falls through to yfinance ingest on miss. Auth-gated. |
| Legacy | `POST /v1/analysis`, `GET /v1/reports/daily/latest`, `GET /v1/forecasts/{symbol}` | ❌ 501 (legacy v1 stubs; will be removed or redirected to `/v1/research`) |

Errors are serialized as [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](../app/core/errors.py). The handler propagates `HTTPException.headers` so `Retry-After` (429) and `WWW-Authenticate` (401) survive the wrap.

## External Integrations (current)

| Service | Purpose | Failure mode |
|---|---|---|
| yfinance | OHLCV, fundamentals, peers, earnings | Defensive `_safe_loc` lookups; missing fields become `None`-valued claims with stable shape |
| SEC EDGAR | Filings (10-K, Form 4, 13F-HR) | Disk-cached; SEC `User-Agent` mandatory; 0.15s sleep between requests for polite-crawl |
| NewsAPI | News articles | Optional — skipped silently when `NEWSAPI_KEY` empty |
| FRED | Macro series | Optional — `fetch_macro` emits metadata claims with None values when `FRED_API_KEY` empty |
| Anthropic Claude | Synth (Sonnet 4.6); triage (Haiku 4.5) wired but currently unused | `RuntimeError` → 503 problem+json (key not configured / provider down) |

Every external call is logged via `log_external_call` (service id, input/output summary, latency ms, timestamp, outcome). See [security.md §A09](security.md#a09) for why.

## Architecture Decisions

ADRs in [docs/adr/](adr/):

- [0001](adr/0001-stack-choice.md) — FastAPI + async SQLAlchemy over Flask/Django.
- [0002](adr/0002-deployment.md) — Deploy to Fly.io + Postgres on Neon.
- [0003](adr/0003-pivot-equity-research.md) — Pivot from v1 (real-time multi-agent platform) to v2 (AI Equity Research Assistant).
- [0004](adr/0004-visual-first-product-shape.md) — Visual-first, delta-driven; not chasing Morningstar-narrative depth.
- [0005](adr/0005-symbol-centric-dashboard.md) — **Read this before proposing surface-shape changes.** Pivot from "click Generate → static report" to symbol-centric dashboard with adaptive layouts (Phase 4).
