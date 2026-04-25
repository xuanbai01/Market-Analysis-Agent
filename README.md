# Market Analysis Agent

An **AI Equity Research Assistant**. POST a ticker, get back a structured analyst-style report — valuation, quality, capital allocation, technicals, recent news, earnings analysis, peer comparison, macro context, insider activity, institutional flows, risk-factor delta — every claim cited and timestamped, built on free data and ~$5/mo of infrastructure.

Live: <https://market-analysis-agent.fly.dev/docs>

> **Status — Phase 1 done, Phase 2 in progress.** Phase 1 (the data + infrastructure layer) is shipped and live: FastAPI + async SQLAlchemy, Postgres on Neon, Fly.io deploy, Alembic migrations, real yfinance ingest with upsert, RSI + SMA technicals, RFC 7807 error handling, A09 external-call logging, 45-test suite, push-to-deploy from `main`. Phase 2 (the agent + tool layer) is being built per [ADR 0003](docs/adr/0003-pivot-equity-research.md). Tracking in [tasks/todo.md](tasks/todo.md).

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
| `POST /v1/news/ingest` | 🟡 No-op stub — Phase 2 wires NewsAPI + RSS providers |
| `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ Real (yfinance ingest with upsert → `candles`; latest-bar with technicals; date-range history) |
| `POST /v1/research/{symbol}` | 🟡 Phase 2 — the v2 primary endpoint |
| `POST /v1/analysis`, `GET /v1/reports/daily/latest`, `GET /v1/forecasts/{symbol}` | ❌ `501 Not Implemented` (legacy v1 routes; will be removed or redirected to `/v1/research`) |

All errors are serialized as [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](app/core/errors.py).

## v2 architecture at a glance

```
POST /v1/research/{symbol}
        │
        ▼
   ┌───────────────────────────────────────────────────────────┐
   │ Default: single agent + tools                              │
   │   triage_call (small model, structured output) picks tools │
   │   synth_call  (capable model, structured output) writes    │
   │                                                            │
   │ Optional: supervisor mode for multi-symbol queries         │
   │   delegates to Research / Technical / Sentiment / Earnings │
   └───────────────────────────────────────────────────────────┘
        │
        ▼  Tool registry (one PR each):
            ✅ fetch_market           ✅ compute_technicals
               fetch_fundamentals        fetch_news
               fetch_edgar               parse_filing
               fetch_earnings            fetch_macro
               fetch_peers               search_history (pgvector)
               compute_options
        │
        ▼
   Pydantic-typed structured report → JSON response
   { sections: list[Section], confidence: "high"|"medium"|"low",
     generated_at: datetime, every claim cites source + fetched_at }
```

- **Language:** Python 3.11, FastAPI 0.115, SQLAlchemy 2.0 (async + asyncpg)
- **DB:** Postgres 15 (Docker locally; Neon free tier in prod) — pgvector enabled for RAG
- **LLM (Phase 2):** Claude Haiku for triage, Sonnet for synthesis (cost-tier routing)
- **RAG (Phase 2):** pgvector on Neon, time-weighted retrieval (`score × e^(-λ × hours)`)
- **Hosting:** Fly.io (auto-stop-machines, ~$0–3/mo idle)

Full detail in [docs/architecture.md](docs/architecture.md), [design_doc.md](design_doc.md), and the [ADRs](docs/adr/).

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
- **Phase 2 — AI Equity Research Assistant** *(in progress)*
  Eval harness + citation-enforcing schema + LLM client with cost-tier routing → tool registry build-out (`fetch_news`, `fetch_fundamentals`, `fetch_edgar`, `parse_filing`, `fetch_earnings`, `fetch_macro`, `fetch_peers`, `search_history` via pgvector RAG, `compute_options`) → `POST /v1/research/{symbol}` with single-agent default + optional supervisor mode. Per-symbol cache + rate limiting before any public exposure. See [ADR 0003](docs/adr/0003-pivot-equity-research.md).
- **Future scope** *(deliberately deferred)*
  Reddit / r/wallstreetbets sentiment, web frontend, Discord bot, real-time scheduled ingest, auth + per-user cost caps. See [tasks/todo.md](tasks/todo.md) for the full deferred list.
