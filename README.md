# Market Analysis Agent

An **AI Equity Research Assistant**. POST a ticker, get back a structured analyst-style report — valuation, quality, capital allocation, technicals, recent news, earnings analysis, peer comparison, macro context, insider activity, institutional flows, risk-factor delta — every claim cited and timestamped, built on free data and ~$5/mo of infrastructure.

Live: <https://market-analysis-agent.fly.dev/docs>

> **Status — Phase 1 + Phase 2 substantively done.** The agent endpoint `POST /v1/research/{symbol}` is live, with a 7-day same-day cache and per-IP rate limit. Real-LLM golden eval passes at factuality ≥ 0.97. Phase 1 (FastAPI + async SQLAlchemy, Postgres on Neon, Fly.io deploy, Alembic, real yfinance ingest, RSI/SMA technicals, RFC 7807 errors, A09 external-call logging, push-to-deploy) shipped first; Phase 2 added the agent layer, 9 free-data tools, citation-enforcing schema, eval harness, cost-tier-routed LLM client. **378 tests passing.** Optional follow-ups (LLM-driven section composition, supervisor mode, pgvector RAG, options snapshots) deliberately deferred — see [design_doc.md](design_doc.md) §Roadmap.

## What this is (and isn't)

| | |
|---|---|
| **Is** | A FastAPI backend that exposes one primary endpoint — `POST /v1/research/{symbol}` — returning a Pydantic-typed structured research report. Single agent + well-designed tools by default; optional supervisor mode for multi-symbol comparisons. |
| **Is** | Built deliberately on **free data only** — yfinance, SEC EDGAR, NewsAPI free tier, FRED — and free-tier infrastructure (Neon Postgres + Fly.io). Real cost: ~$0–5/mo. |
| **Isn't** | A real-time market platform. The original v1 vision (15-min news firehose, Discord bot, multi-agent-as-architecture) was [explicitly cut](docs/adr/0003-pivot-equity-research.md) in favour of depth-over-freshness and the modern *single-agent + tools* pattern. |
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
| `POST /v1/research/{symbol}?focus={full,earnings}&refresh={false,true}` | ✅ **The v2 primary endpoint.** 7 sections in `full` mode (Valuation, Quality, Capital Allocation, Earnings, Peers, Risk Factors, Macro) or 3 in `earnings`. Same-day cache (default 7 days, configurable) + per-IP rate limit (default 3/hour, configurable). |
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
| `search_history` | pgvector RAG | 🟡 Phase 3 |
| `compute_options` | yfinance options + daily IV snapshots | 🟡 Phase 3 |

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
│   ├── main.py                  # app factory + router mounting
│   ├── core/                    # settings, logging, errors, observability (A09 helper)
│   ├── api/v1/
│   │   ├── dependencies.py      # DB session DI
│   │   └── routers/             # one file per route group
│   ├── db/
│   │   ├── session.py           # async engine + sessionmaker
│   │   └── models/              # Symbol, NewsItemModel, Candle
│   ├── schemas/                 # Pydantic request/response models
│   └── services/                # repositories, ingestion, technicals (Phase 2: agent.py, tools/, evals/)
├── alembic/                     # schema migrations (async)
│   ├── env.py
│   └── versions/                # one file per migration; `alembic upgrade head` applies all
├── tests/                       # pytest-asyncio; function-scoped DB with SAVEPOINT rollback
├── docs/                        # architecture, security, testing, commands, deployment, ADRs
├── tasks/                       # active sprint (todo.md) + lessons learned
├── design_doc.md                # long-form system design (v2 scope at top, v1 preserved below)
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
- **Phase 2 — AI Equity Research Assistant** ✅ *(substantively complete)*
  - 2.0 Foundations: citation-enforcing schema, LLM client with cost-tier routing, eval harness with rubric (structure / factuality / latency).
  - 2.1 Tool registry: `fetch_news`, `fetch_fundamentals`, `fetch_peers`, `fetch_edgar`, `parse_filing` (Form 4 + 13F + 10-K business + 10-K risks YoY diff), `fetch_earnings`, `fetch_macro` — 9 of 9 active tools shipped.
  - 2.2 Agent + endpoint: `POST /v1/research/{symbol}` with deterministic-everything-except-prose architecture; same-day cache (default 7-day window); per-IP rate limit (default 3/hour). Real-LLM golden eval at factuality 0.97.
  - 2.2d / 2.3 (deferred): LLM-driven section composition + supervisor mode for multi-symbol queries — only land if the rubric shows the deterministic catalog is too rigid. No signal that this is needed yet.
- **Phase 3 — stretch / future scope** *(deliberately deferred)*
  - `search_history` (pgvector RAG over stored news + filings, time-weighted)
  - `compute_options` (yfinance option_chain + daily IV snapshot job, IV percentile + implied move)
  - Web frontend / Discord client
  - Auth + per-user cost caps + horizontal-scale rate limit (Redis swap-in)
  - Reddit / r/wallstreetbets sentiment (only if a recurring eval query justifies it)

See [tasks/todo.md](tasks/todo.md) for the granular tracker, [design_doc.md](design_doc.md) for system design, and [ADR 0003](docs/adr/0003-pivot-equity-research.md) for the v1→v2 pivot rationale.
