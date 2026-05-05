# Market Analysis Agent

An **AI Equity Research Assistant**. POST a ticker, get back a structured analyst-style report — valuation, quality, capital allocation, technicals, recent news, earnings analysis, peer comparison, macro context, insider activity, institutional flows, risk-factor delta — every claim cited and timestamped, built on free data and ~$5/mo of infrastructure.

Live: <https://market-analysis-agent.fly.dev/docs>

> **Status — Phases 1 → 4.5 done; Phase 4.6 (Compare page) is next.** The agent endpoint `POST /v1/research/{symbol}` is live with a 7-day same-day cache and per-IP rate limit; real-LLM golden eval passes at factuality ≥ 0.97. Phase 4 (the symbol-centric dashboard rebuild per [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md)) shipped 4.0 → 4.5.C: dashboard route at `/symbol/:ticker`, hand-rolled SVG primitives (Sparkline, LineChart, EpsBars, MetricRing, MultiLine, PeerScatterV2), nine dedicated cards (Hero, Quality, Earnings, Valuation, PerShareGrowth, CashAndCapital, RiskDiff, Macro, plus Business + News in a ContextBand), per-card LLM-written narratives, and adaptive layouts that reframe distressed names (Rivian-class) around survival rather than quality. Frontend Vercel deploy held until **Phase 4.8 dogfood gate**. See [tasks/todo.md](tasks/todo.md) for the granular tracker. **607 tests passing on the backend, 392 on the frontend; main bundle 98.42 KB gzipped (under 100 KB budget).**

## What this is (and isn't)

| | |
|---|---|
| **Is** | A FastAPI backend exposing one primary endpoint — `POST /v1/research/{symbol}` — returning a Pydantic-typed structured research report. Single agent + well-designed tools, deterministic section composition, LLM only writes the per-section summary prose under a forced schema. React + Vite frontend renders the report as cards + (Phase 3) charts. |
| **Is** | Built deliberately on **free data only** — yfinance, SEC EDGAR, NewsAPI free tier, FRED — and free-tier infrastructure (Neon Postgres + Fly.io). Real cost: ~$0–5/mo. |
| **Is** | **Visual-first, delta-driven** per [ADR 0004](docs/adr/0004-visual-first-product-shape.md). Multi-year history rendered as charts; LLM commentary stays short and stays at judgment-dependent moments (e.g. 10-K risk-factor changes). |
| **Isn't** | A real-time market platform. The original v1 vision (15-min news firehose, Discord bot, multi-agent-as-architecture) was [explicitly cut](docs/adr/0003-pivot-equity-research.md) in favour of depth-over-freshness. |
| **Isn't** | A Morningstar-shaped analyst note. Multi-year DCF projections, fair-value estimates, capital-allocation letter grades, 5-page bull/bear essays — all explicitly out of scope (ADR 0004 §"Option 1 rejected"). The toolkit (free data + LLM) is the wrong shape for those. |
| **Isn't** | A trading signal generator. Reports are research-style synthesis, not buy/sell recommendations. Every claim cites its source so a human can verify before acting. |

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
uv sync                            # install pinned deps (Python 3.11 via .python-version)
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
| `POST /v1/news/ingest` | ✅ Real — NewsAPI dev tier + Yahoo per-ticker RSS, symbol tagging, `news_symbols` join |
| `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ Real (yfinance ingest with upsert → `candles`; latest-bar with technicals; date-range history) |
| `GET /v1/market/{symbol}/prices?range={60D\|1Y\|5Y}` | ✅ **Phase 4.1.** Read-through `candles` cache; falls through to yfinance ingest on miss with 80%-coverage threshold. Auth-gated. Powers the dashboard hero price chart. |
| `POST /v1/research/{symbol}?focus={full,earnings}&refresh={false,true}` | ✅ **The v2 primary endpoint.** 9 sections in `full` mode (Business, News, Valuation, Quality, Capital Allocation, Earnings, Peers, Risk Factors, Macro) or 4 in `earnings` (News, Earnings, Valuation, Risk Factors). Same-day cache (default 7 days, configurable) + per-IP rate limit (default 3/hour, configurable). Phase 4.4.B added `Section.card_narrative` for per-card 1-2 sentence headlines; Phase 4.5.A added `ResearchReport.layout_signals` for adaptive-layout flags. |
| `GET /v1/research?limit=20&offset=0&symbol=...` | ✅ Paginated `ResearchReportSummary[]` for the dashboard sidebar. |
| `POST /v1/analysis`, `GET /v1/reports/daily/latest`, `GET /v1/forecasts/{symbol}` | ❌ `501 Not Implemented` (legacy v1 routes; will be removed or redirected to `/v1/research`) |

All errors are serialized as [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](app/core/errors.py).

### Hitting the research endpoint

```bash
# In .env: ANTHROPIC_API_KEY=sk-ant-... (required)
# In .env: FRED_API_KEY=... (optional — Macro section degrades gracefully without it)

uv run uvicorn app.main:app --reload

# Cold call: ~30 s, full LLM round trip + tool fan-out
curl -X POST http://localhost:8000/v1/research/AAPL -o report.json

# Same call within 7 days: ~10 ms, served from research_reports table
curl -X POST http://localhost:8000/v1/research/AAPL -o report-cached.json

# Force fresh synthesis (consumes 1 rate-limit token + ~$0.10 LLM cost)
curl -X POST "http://localhost:8000/v1/research/AAPL?refresh=true" -o report-fresh.json
```

Spot-check the data layer end-to-end without the LLM via [`scripts/smoke.py`](scripts/smoke.py):

```bash
uv run python scripts/smoke.py AAPL --skip-13f
```

Runs each Phase 2 tool against live providers (yfinance, SEC EDGAR, FRED) and prints a one-line summary per tool — fast way to verify nothing has drifted upstream before the agent runs.

## v2 architecture at a glance

```
POST /v1/research/{symbol}?focus=full
        │
        ▼
   Cache lookup (research_reports, configurable window, default 7d)
        │   hit  → return (no LLM, no token consumed) ─┐
        │ miss                                         │
        ▼                                              │
   Rate limit (per-IP token bucket, default 3/hour)    │
        │   deny → 429 + Retry-After                   │
        │ pass                                         │
        ▼                                              │
   Orchestrator (deterministic-everything-except-prose)│
   ─ runs every focus-required tool in parallel        │
   ─ static SECTION_TO_CLAIM_KEYS — code picks claims, │
     not the LLM                                       │
   ─ Sonnet writes only the 2-4 sentence summaries     │
     under a forced SectionSummaries schema            │
   ─ confidence stamped programmatically per section   │
        │                                              │
        ▼                                              │
   Cache upsert  (overwrites same-day row)             │
        │                                              │
        ▼                                              │
   Pydantic-typed structured report ◀──────────────────┘
   { sections: list[Section{claims, summary, confidence}],
     overall_confidence: "high"|"medium"|"low",
     tool_calls_audit: ["fetch_fundamentals: ok", ...],
     generated_at: datetime — every claim cites source + fetched_at }
```

**Tool registry** (every tool is a focused async function returning `dict[str, Claim]` or a typed Pydantic record; all wrapped in `log_external_call`):

| Tool | Source | Status |
|---|---|---|
| `fetch_market`, `compute_technicals` | yfinance OHLCV + in-memory RSI/SMA | ✅ |
| `fetch_news` | NewsAPI dev + Yahoo per-ticker RSS, symbol tagger | ✅ |
| `fetch_fundamentals` | yfinance.info + financials/cashflow | ✅ |
| `fetch_peers` | curated sector map + yfinance fallback | ✅ |
| `fetch_edgar` | SEC EDGAR with disk cache + polite-crawl | ✅ |
| `parse_filing` | Form 4 cluster, 13F holdings, 10-K Item 1, 10-K risks YoY diff | ✅ |
| `fetch_earnings` | yfinance earnings dates + consensus | ✅ |
| `fetch_macro` | FRED API + sector→series map | ✅ (graceful no-op without `FRED_API_KEY`) |
| `search_history` | pgvector RAG | ⏸ deferred (ADR 0004) |
| `compute_options` | yfinance options + daily IV snapshots | ⏸ deferred (ADR 0004) |

- **Language:** Python 3.11, FastAPI 0.115, SQLAlchemy 2.0 (async + asyncpg)
- **DB:** Postgres 15 (Docker locally; Neon free tier in prod). pgvector lands when `search_history` does.
- **LLM:** Claude Haiku 4.5 for triage (currently unused — section composition is deterministic; the client is wired and ready), Claude Sonnet 4.6 for synthesis. System prompts are cached (`cache_control: ephemeral`) for cost savings on repeat shape.
- **Hosting:** Fly.io (auto-stop machines, ~$0–3/mo idle)

Full detail in [docs/architecture.md](docs/architecture.md), [design_doc.md](design_doc.md), and the [ADRs](docs/adr/).

### Rate limit posture (current choice — easy to flip)

The rate-limit check on `/v1/research/{symbol}` runs **after** the cache lookup, not before. **Cache hits do not consume rate-limit tokens** — only cache misses and `?refresh=true` calls do. The reasoning: the rate limit exists to bound *LLM cost*, and a cache hit costs nothing.

This is the right posture for a personal-scale deployment where re-reading your own already-generated reports shouldn't trigger 429s. Trade-off: a determined attacker who has burned 3 tokens can still hit the cache lookup endpoint indefinitely. For the current single-user use case that's fine — cache lookups are sub-millisecond indexed SELECTs and there's exactly one user.

**If/when this goes public-multi-user**, flipping back to "every request consumes a token" is a one-line change: add `dependencies=[Depends(enforce_research_rate_limit)]` to the `@router.post` decorator in [`app/api/v1/routers/research.py`](app/api/v1/routers/research.py) and remove the explicit `await enforce_research_rate_limit(request)` call inside the route. Tests `test_cache_hits_do_not_consume_rate_limit_tokens` and `test_rate_limit_runs_after_cache_miss_only` would need to be deleted or inverted.

History: implemented "every request" first (PR #29), flipped to "post-cache" in the follow-up PR after the live verification showed the every-request behavior was wrong for personal use. Both behaviors are tested in this commit's history if a future maintainer needs to compare.

### Anti-hallucination disciplines (non-negotiable Phase 2 success criteria)

A research-report agent that produces beautifully-formatted hallucinations is worse than no agent. Every Phase 2 PR is gated on:

1. **Citation discipline** — every claim cites the tool call that produced it. The structured-output schema enforces it; the agent cannot synthesize free-form text.
2. **Per-section confidence** (`high | medium | low`) set programmatically based on data freshness, sparsity, and fall-back paths.
3. **Eval harness** — golden questions auto-graded on factuality + structure + latency. Regressions fail CI.
4. **`last_updated` per data point** so stale data does not masquerade as fresh.

## Repository layout

```
/
├── app/                         # FastAPI application
│   ├── main.py                  # app factory, CORS, error handlers, router mounting
│   ├── core/                    # settings, auth, cors, errors, observability (A09 helper)
│   ├── api/v1/
│   │   ├── dependencies.py      # DB session DI, rate limit
│   │   └── routers/             # health, symbols, news, market, research
│   ├── db/
│   │   ├── session.py           # async engine + sessionmaker
│   │   └── models/              # Symbol, NewsItemModel, NewsSymbol, Candle, ResearchReportRow
│   ├── schemas/                 # Pydantic request/response (research.py is the v2 schema)
│   └── services/                # tools (fetch_*, parse_*), orchestrator, layout signals,
│                                # research_cache, rate_limit, llm
├── alembic/versions/            # 0001 baseline, 0002 news_symbols, 0003 research_reports
├── frontend/                    # Vite + React 18 + TS dashboard
│   ├── src/
│   │   ├── components/          # SymbolDetailPage, HeroCard, QualityCard, EarningsCard,
│   │   │                        # ValuationCard, PerShareGrowthCard, CashAndCapitalCard,
│   │   │                        # RiskDiffCard, MacroPanel, BusinessCard, NewsList,
│   │   │                        # ContextBand, HeaderPills, NarrativeStrip, primitives
│   │   │                        # (LineChart, EpsBars, MetricRing, MultiLine, PeerScatterV2)
│   │   └── lib/                 # Zod schemas, API client, extractors, format helpers
│   └── vercel.json              # Vercel deploy config (held until 4.8)
├── tests/                       # pytest-asyncio; per-test SAVEPOINT rollback. Plus tests/evals/
├── docs/                        # architecture, security, testing, commands, ADRs (0001 → 0005)
├── tasks/                       # active sprint (todo.md), lessons learned, dogfood notes
├── scripts/                     # smoke.py — exercises each tool against live providers
├── design_doc.md                # long-form system design
├── fly.toml                     # Fly.io app config
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
| Apply migrations | `uv run alembic upgrade head` |

More commands in [docs/commands.md](docs/commands.md).

## CI

Every PR runs (see [.github/workflows/ci.yml](.github/workflows/ci.yml)):

- **Backend — Unit Tests:** `ruff` + `pytest` against an ephemeral Postgres service container.
- **Secrets Scan (Gitleaks):** blocks committed secrets.
- **AI PR Review (Claude):** posts an inline review on the PR.

Phase 2 will add an **Eval harness** job that runs the golden-question suite and fails the build on factuality regressions.

## Deployment

Target: **Fly.io** for the API, **Neon** for Postgres. Both on free tiers until traffic warrants. Rationale in [ADR 0002](docs/adr/0002-deployment.md); first-time setup and ongoing ops in [docs/deployment.md](docs/deployment.md).

Push-to-deploy via [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) — `git push origin main` runs `flyctl deploy --remote-only`. The deployed container runs `alembic upgrade head` before `uvicorn`, so schema migrations apply on every rollout.

## Contributing

This is a personal learning / portfolio project, but PRs are welcome. If you're opening one:

1. Read [docs/workflow.md](docs/workflow.md) — TDD is non-negotiable for business logic.
2. Read [docs/security.md](docs/security.md) — especially A09 on logging every external call.
3. Open a PR against `main`. The C.L.E.A.R. checklist in [the PR template](.github/pull_request_template.md) is enforced by review.

## License

No license file yet. Treat as all-rights-reserved until one lands.

## Roadmap

- **Phase 1 — Core Infrastructure** ✅ *(complete)*
  FastAPI + Alembic + tests + real yfinance ingest + RSI/SMA technicals + Fly + Neon + push-to-deploy.
- **Phase 2 — AI Equity Research Assistant** ✅ *(complete)*
  Citation-enforcing schema, 9 free-data tools, deterministic-everything-except-prose orchestrator, same-day cache, per-IP rate limit, real-LLM golden eval at factuality 0.97.
- **Phase 3 — Visual-first depth** ✅ *(complete; PRs #35 → #44)*
  `Claim.history` schema extension; `fetch_fundamentals` / `fetch_earnings` / `fetch_macro` ship multi-period histories; eval rubric reads `claim.history` for trend-prose factuality. Frontend sparklines + section charts shipped via the v1 dashboard before being replaced by the Phase 4 Strata redesign.
- **Phase 4 — Symbol-centric dashboard rebuild** 🔄 *(in flight; 4.5.C ready for review at PR #59; 4.6 next)*
  Per [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md). The dashboard pivoted from "click Generate → static report" to a `/symbol/:ticker` URL-routed dashboard with adaptive layouts:
  - **4.0 → 4.4 done (PRs #46 → #56):** Strata token system, `react-router-dom@6`, `SidebarShell` + `LandingPage` + `SymbolDetailPage`. Hand-rolled SVG primitives (LineChart, EpsBars, MetricRing, MultiLine, PeerScatterV2). Nine dedicated cards: Hero (price + featured stats), Quality, Earnings (20Q EPS bars + recent prints), Valuation (4-cell + peer scatter), PerShareGrowth (5 series rebased), CashAndCapital, RiskDiff (per-category Haiku categorizer), MacroPanel, plus Business + News in a ContextBand. Per-card LLM-written `card_narrative` field with the eval rubric policing both that and the broader `summary`.
  - **4.5 done (PRs #57 → #59):** adaptive layout. `LayoutSignals` model + pure derivation read claim values to detect distress (`is_unprofitable_ttm`, `beat_rate_below_30pct`, `cash_runway_quarters`, `gross_margin_negative`, `debt_rising_cash_falling`). HeaderPills above hero ("● UNPROFITABLE · TTM", "⚠ LIQUIDITY WATCH"); HeroCard right-column trio swap (Forward P/E → P/Sales, ROIC → Cash Runway, FCF margin red on negative); EarningsCard "bottom decile" pill; CashAndCapitalCard runway tile + "raise likely needed"; QualityCard rings flip red on negative ratios; SymbolDetailPage row 3/4 reorder so Cash + Risk + Macro lift above Valuation + Growth on distressed names; Sonnet's prompt receives signals as framing context. Layout polish (4.5.C): wider `max-w-screen-2xl` container, `items-start` honest-height alignment, ContextBand to bottom, auto-collapsing row 4.
  - **4.6 next — Compare page (`/compare?a=NVDA&b=AVGO`)**: two-ticker side-by-side dashboard with overlay charts. Bundle headroom is currently 1.58 KB so the new route needs `React.lazy()` chunk-splitting. Plan in `tasks/todo.md` §4.6.
  - **4.7 — Search modal + Watchlist + Recent**: `⌘K` modal, localStorage watchlist, recent ticker tracking, landing-page upgrade.
  - **4.8 — Vercel deploy + dogfood gate**: ship the frontend; dogfood across 8–10 real symbols; the dogfood signal decides whether to escalate to Phase 5 (Narrative layer) or Phase 6 (XBRL Tier 2).
- **Phase 5 — Narrative layer** ⏸ *(deferred; conditional on 4.8 dogfood signal)*
  Explicit Bulls Say / Bears Say with `claim_refs` enforcement, What Changed deltas, `?focus=thesis`. Lands only if 4.8 surfaces "I want a real bull/bear case" repeatedly that the per-card narratives don't satisfy.
- **Phase 6 — XBRL Tier 2** ⏸ *(deferred; conditional on 4.8 dogfood signal)*
  Segment + geography revenue breakdowns, RPO via XBRL parser. Lands if 4.8 surfaces "I need segment/geography breakdowns" repeatedly (esp. for names where segment mix is the story — NVDA Data Center vs Gaming, AMZN AWS vs Retail).
- **Indefinitely deferred** ⏸
  `search_history` (pgvector RAG), `compute_options` (yfinance + daily IV snapshot), Reddit sentiment, real auth + per-user cost caps + Redis-backed horizontal rate limit. Revisit when there's a concrete trigger.

See [tasks/todo.md](tasks/todo.md) for the granular tracker, [design_doc.md](design_doc.md) for system design, [ADR 0003](docs/adr/0003-pivot-equity-research.md) for the v1→v2 pivot, [ADR 0004](docs/adr/0004-visual-first-product-shape.md) for the visual-first commitment, and [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md) for the Phase 4 dashboard pivot.
