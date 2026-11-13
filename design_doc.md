# Financial Market Analysis Agent — Design

> **Status:** v2 — **AI Equity Research Assistant**, Phases 1–5 done (2026-11). Dashboard live at <https://market-analysis-agent-red.vercel.app> (shared-secret sign-in, internal use), API at <https://market-analysis-agent.fly.dev>. Pivoted from the v1 "real-time multi-agent platform" in [ADR 0003](docs/adr/0003-pivot-equity-research.md); **visual-first, delta-driven** per [ADR 0004](docs/adr/0004-visual-first-product-shape.md); a **symbol-centric dashboard** per [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md); prose that **interprets** per [ADR 0007](docs/adr/0007-analytical-narratives.md). This doc is the single source of truth for scope, architecture and roadmap; the v1 design lives in git history.

## Goal

Given a US-equity ticker, show a fully cited research dashboard — price, quality, earnings, valuation against peers, per-share growth, cash and capital returns, 10-K risk-factor changes, macro, business and news — with multi-year history drawn as charts, short prose that says what the numbers mean, and an analyst view that argues the bull and bear case from the report's own numbers. The agent calls free-data tools, the schema enforces citations, code computes every comparison, and the eval harness gates regressions.

Two real workflows the system serves:

1. **Long-term value diligence** — research before adding or trimming a position.
2. **Catalyst-aware position sizing** — knowing what just changed (risk-factor diffs, EPS trend, margin moves, peer gaps, recent news) before sizing in or out.

A third, added by the lenses: **cross-company context** — how a metric is distributed across a group (e.g. megacap capex intensity) and what that says about one company in it.

Cost target: **$5–15 / month all-in** (free-tier infra + free data + per-call LLM). Actual: ~$0–5/mo; a fresh report costs about a cent on DeepSeek Flash.

## Scope

**In:** research dashboards on US-listed equities, generated on demand and cached up to 7 days; two-ticker compare; cross-company lenses from SEC XBRL; a headline-markets strip.

**Out:** real-time feeds, intraday alerts, scheduled news firehose, Discord client, options analytics without IV history, portfolio orchestration, Reddit sentiment, buy/sell recommendations, DCF / fair-value estimates.

## Architecture (current)

```
Browser (Vercel: React 18 + Vite, TanStack Query, Zod)
    │  Authorization: Bearer <shared secret>; CORS allows one origin
    ▼
┌─────────────────────────────────────────────────────────┐
│ FastAPI 0.115 on Fly.io — async SQLAlchemy 2.0 + asyncpg│
│ RFC 7807 errors · log_external_call on every call out   │
└─────────────────────────────────────────────────────────┘
    │
    ├── POST /v1/research/{symbol}
    │     cache lookup ─▶ rate limit (miss only) ─▶ orchestrator
    │       ├ data tools in parallel (asyncio.gather, exceptions captured)
    │       ├ deterministic claim builders + derived comparisons
    │       ├ LLM, two calls in parallel, forced schemas:
    │       │    section prose  ·  analyst view (claim-id citations)
    │       ├ citation check in code; confidence + layout signals
    │       └ cache upsert (research_reports, JSONB)
    │
    ├── GET /v1/lens/{id}       SEC XBRL ─▶ window + stats + facts ─▶ cited read
    ├── GET /v1/market/overview headline quotes + fear & greed estimate
    ├── GET /v1/market/{symbol}/prices   candles cache, yfinance on miss
    └── Phase 1 data routes (symbols, news, market ingest/history)
```

Layering: `router → service → repository / external`. Business logic never lives in routers. Per-file map in [docs/architecture.md](docs/architecture.md).

### Storage

- **Postgres on Neon** (managed, autosuspend); schema in `alembic/versions/`.
- **Disk caches** for SEC responses (filings, XBRL company concepts; 24 h for XBRL).
- **In-memory TTL caches** for the market strip (5 min quotes, 1 h sentiment) and lenses (24 h), each serving the last good value when a refresh fails.
- **No Redis, no Celery, no scheduled cron.** Re-introduced only if a real workload forces it.

### Hosting

- **Fly.io** — shared-CPU 512 MB machine, region IAD, auto-stop (first request after idle wakes it). Deploys on push to `main`; the container runs `alembic upgrade head` before `uvicorn`.
- **Vercel** — builds `frontend/` on push to `main`; `VITE_BACKEND_URL` points at Fly.
- **Neon** — Postgres free tier. Rationale for Fly + Neon in [ADR 0002](docs/adr/0002-deployment.md); runbook in [docs/deployment.md](docs/deployment.md).

## Tech stack (current pins)

| Layer | Tech |
|---|---|
| Language | Python 3.11 (backend), TypeScript 5.6 (frontend) |
| Web framework | FastAPI 0.115 |
| ORM / migrations | SQLAlchemy 2.0 (async) + asyncpg · Alembic 1.13 |
| Validation | Pydantic 2.9 (backend) · Zod (frontend mirrors) |
| LLM | Switchable via `LLM_PROVIDER` ([ADR 0006](docs/adr/0006-pluggable-llm-provider.md)): Anthropic SDK (Haiku 4.5 triage + Sonnet 4.6 synth; code default) or DeepSeek V4.1 Flash via the `openai` SDK (production) |
| Market data | yfinance 1.3 |
| Filings | SEC EDGAR (filings + XBRL company-concept API) |
| News | Yahoo per-ticker RSS + NewsAPI free tier |
| Macro | FRED |
| Frontend | React 18 + Vite + Tailwind + TanStack Query + react-router 6; hand-rolled SVG charts |
| Database | PostgreSQL 15 (Docker locally; Neon in prod) |
| Hosting | Fly.io (API) + Vercel (dashboard) |
| Tests | pytest 8.3 + pytest-asyncio · vitest + happy-dom |
| Lint | ruff · ESLint + `tsc` |
| CI | GitHub Actions: backend, frontend, production-image boot, Gitleaks, AI PR review |

**Deliberately not used:** LangChain, Celery, Redis, Pinecone, a charting library (the charts are hand-rolled SVG; Recharts was removed in 2026-11). The single-agent-with-tools pattern doesn't need them.

## Data model

| Table | Columns | Indexes | Notes |
|---|---|---|---|
| `symbols` | `symbol` (PK), `name` | — | Seeded with NVDA, SPY; upserted before any candle or news write. |
| `candles` | `(symbol, ts, interval)` PK; OHLCV; FK on `symbol` | `(symbol, interval, ts DESC)` | Append-only; read-through cache for the price chart. |
| `news_items` | `id` (`sha256(url)`) PK, `ts`, `title`, `url`, `source` | `ts DESC` | Hash id collapses duplicates across providers. |
| `news_symbols` | `(news_id, symbol)` composite PK; cascading FKs | `(symbol, news_id)` | Tags articles to symbols. |
| `research_reports` | `(symbol, focus, report_date)` PK; `report_json` JSONB; `generated_at` | — | Report cache; lookup windowed by `generated_at` (`RESEARCH_CACHE_MAX_AGE_HOURS`). |

**Report shape** (`app/schemas/research.py`): `ResearchReport { symbol, name, sector, sections[Section{title, claims[Claim{description, value, unit, source, history[]}], summary, card_narrative, confidence}], thesis: Thesis | None, layout_signals, overall_confidence, tool_calls_audit, generated_at }`. New fields always default so cached rows round-trip unchanged.

## Tools and derived claims

Tools live in `app/services/`. Each is a focused async function; sync providers run in `asyncio.to_thread`; every external call is wrapped in `log_external_call`. Tests mock at the provider registry, not at the network.

| Tool | Source | Feeds |
|---|---|---|
| `fetch_fundamentals` | yfinance info + quarterly statements | Hero, Quality, Capital Allocation, Valuation |
| `fetch_earnings` | yfinance earnings dates (20 quarters) | Earnings |
| `fetch_peers` | curated sector map + yfinance fallback | Valuation, Peers |
| `fetch_macro` | FRED, sector → series map | Macro |
| `extract_10k_business` / `extract_10k_risks_diff` | SEC EDGAR 10-K; risk paragraphs categorized by triage LLM | Business, Risk Factors |
| `fetch_business_info` | yfinance summary, HQ, employees | Business |
| `fetch_news` | Yahoo RSS + NewsAPI, ingested per report, categorized by triage LLM | News |
| `xbrl.annual_series` | SEC company-concept API (tags merged per year, CY frames) | Lenses |
| `fetch_annual_history` | SEC XBRL annual facts, split-adjusted with yfinance splits | Quality (ten-year per-share growth) |
| `parse_filing` (Form 4, 13F), `compute_technicals` | Phase 2 parsers, RSI/SMA | not on the dashboard today |

**Derived claims** (`app/services/research_derived.py`, ADR 0007) are computed in code and added to sections with source `computed.analytics`: year-over-year margin and per-share changes between named quarters, TTM FCF margin and yield, FCF ÷ net income, payout, shareholder yield, dividend coverage, capex intensity, SBC ÷ FCF, net debt ÷ operating cash flow, premium or discount to the peer median, implied EPS growth, beat streak, latest surprise vs average. Banks skip FCF, capex, gross margin and net debt. These give the model comparisons to argue from without ever computing a number itself.

**Layout signals** (`research_layout_signals.py`): unprofitable TTM, beat rate under 30%, cash runway in quarters, negative gross margin, debt rising while cash falls. They drive header pills, the hero metric swap and the distressed card order, and frame the prompt.

## LLM strategy

- **Provider switch.** `LLM_PROVIDER=anthropic|deepseek` at call time; `LLM_TRIAGE_MODEL` / `LLM_SYNTH_MODEL` override per tier. Production runs DeepSeek Flash with thinking disabled; the code default stays Anthropic.
- **Two tiers.** Triage: the risk-paragraph and news categorizers (unknown categories map to OTHER). Synth: section prose, the analyst view, the lens read.
- **Forced schemas.** Every call fills one named function/tool whose schema is the Pydantic model — no free-form parsing path.
- **What the prompt carries.** Each claim in display units with its history (first → last, low, high), the sector (with a bank note), layout signals when distressed, and the rules: lead with the conclusion, argue from the given comparisons, never compute a number, no outside facts.
- **Analyst view** (`research_thesis.py`): claims are tagged with ids (`[Q3]`); ids resolve to `ClaimRef(section, index)`; a cited claim counts only if the point quotes one of its values at the quoted precision; uncited points are dropped; any failure leaves `thesis=None`. News headlines are excluded as inputs.
- **No user input is interpolated into prompts.** The symbol comes from the validated path; everything else is structured tool output. See [docs/security.md](docs/security.md) A03.

## Anti-hallucination disciplines

Non-negotiable; every PR is held to them.

1. **Citation discipline.** `Source` is frozen (`tool, fetched_at, url, detail`); `Claim` carries `value + unit + source + history`. Free text exists only in `summary`, `card_narrative`, thesis points and the lens read, and each is checked against claims.
2. **Code computes, the model writes.** Comparisons are derived claims; the prompt forbids arithmetic.
3. **Per-section confidence** set programmatically from freshness and sparsity, never by the LLM.
4. **Eval harness.** [`tests/evals/`](tests/evals/): rubric unit tests on every PR (free); the live golden eval (AAPL, NVDA, RIVN, JPM, KO, XOM) is opt-in with `-m live_llm` or the Live Eval workflow. The factuality rubric reads unit-suffixed numbers whole, accepts history values, and covers summaries, card narratives and the analyst view. Latest live run on DeepSeek: 1.000 on all five.
5. **`fetched_at` per data point** — the wall time the upstream call returned.

## API surface

| Group | Routes | Auth (when `BACKEND_SHARED_SECRET` is set) |
|---|---|---|
| Health | `GET /v1/health` | open |
| Research | `POST /v1/research/{symbol}?focus={full,earnings}&refresh=`, `GET /v1/research` | bearer |
| Market | `GET /v1/market/{symbol}/prices?range=`, `GET /v1/market/overview`, `POST /v1/market/ingest` | bearer |
| Market (Phase 1 reads) | `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | open |
| Lenses | `GET /v1/lens`, `GET /v1/lens/{id}` | bearer |
| Symbols / News | `GET /v1/symbols`, `GET /v1/news`, `GET /v1/news/{id}` open; `POST /v1/symbols`, `POST /v1/news/ingest` bearer | |

Errors are RFC 7807 problem+json via [`app/core/errors.py`](app/core/errors.py); `Retry-After` (429) and `WWW-Authenticate` (401) survive the wrap.

## Cost model

| Item | Monthly | Notes |
|---|---|---|
| Fly.io shared-CPU 512 MB | $0–5 | Auto-stop; idle cost ~$0 |
| Neon free tier | $0 | 0.5 GB storage, autosuspend |
| Vercel hobby | $0 | Static build |
| LLM | $0–5 | ~1¢ per fresh report on DeepSeek Flash (two synth calls + categorizers); cache hits free |
| NewsAPI / FRED / SEC / yfinance | $0 | Free tiers |
| **Estimated total** | **$0–10** | Well inside the original $50–80 budget |

The per-IP rate limit on fresh reports (default 3/h; 30/h in production during dogfooding) runs after the cache lookup, so re-reading a report is free. Lower it before the URL is shared.

## Security

Active OWASP mitigations in [docs/security.md](docs/security.md). The non-negotiables:

- **A01 access.** Shared-secret bearer auth on every route that costs money, spends quota or writes; single-origin CORS.
- **A09 observability.** Every external call (LLM, yfinance, SEC, FRED, news) logged with service id, input/output shape, latency, timestamp and outcome via `log_external_call`.
- **A03 injection.** No user input in SQL strings (typed `select()`) or LLM prompts (structured slots only).
- **Honest clients.** No bot-check circumvention: CNN's fear & greed endpoint refuses automated clients, so the strip shows our own labelled estimate instead.

Real auth and per-user cost caps land only when there are real users.

## Roadmap

**Phase 1 — Core infrastructure (done).** FastAPI scaffold, async DB stack, Alembic, yfinance ingest, technicals, observability, RFC 7807, Fly + Neon, CI.

**Phase 2 — Equity research assistant (done).** Citation-enforcing schema, free-data tools, deterministic-everything-except-prose orchestrator, report cache, per-IP rate limit, golden eval.

**Phase 3 — Visual-first depth (done; PRs #35 → #44).** `Claim.history`, multi-period fundamentals / earnings / macro, history-aware rubric.

**Phase 4 — Symbol-centric dashboard (done; PRs #46 → #82).** Per ADR 0005.
- **4.0 → 4.7:** Strata tokens, router, dedicated cards and hand-rolled SVG charts, per-card narratives, adaptive layouts for distressed names, Compare, search / watchlist / recent, lazy route chunks.
- **4.8 deploy + dogfood gate (2026-11):** locked every costly route behind the shared secret, news ingested per report, frontend + image CI jobs, Fly + Vercel + DeepSeek in production. Dogfooding (AAPL, NVDA, MSFT, AVGO, KO, RIVN, JPM) fixed prose units, chart readability (axes, baselines, $/share panels, stat tiles), the sidebar, report freshness (Regenerate), error boundaries and the card layout (full-width big cards, one equal-height row of small cards, sticky section nav, Capital returns card), and added the market strip. Log: [tasks/dogfood-2026-11.md](tasks/dogfood-2026-11.md).
- **Gate decision:** the owner's verdict was that the cards "just display data" and asked for deeper, cross-company analysis — the Phase 5 signal. Segment and geography breakdowns did not come up, so Phase 6 stays deferred.

**Phase 5 — Narrative layer (done, as ADR 0007).** Derived comparison claims + interpretive card prose; the cited analyst view (bull / bear / changed / watch); lenses, starting with megacap tech capex. A separate `?focus=thesis` mode wasn't needed — the analyst view rides on full reports.

**Phase 6 — XBRL Tier 2 (deferred).** Segment and geography revenue, RPO. The lens XBRL client is the starting point. Escalate if dogfooding asks for segment mix (NVDA Data Center vs Gaming, AMZN AWS vs Retail).

**Next (plan in [tasks/todo.md](tasks/todo.md), 2026-11-13):** valuation against the company's own ten-year history; a public read-only demo and README screenshots, with the production rate limit lowered alongside; then more lenses and insider activity from the Form 4 parser. A compare narrative (4.6.B) waits until Compare gets used.

**Indefinitely deferred.** `search_history` (pgvector RAG), `compute_options`, Reddit sentiment, real auth + per-user cost caps + Redis-backed rate limiting.

## Risks

| Risk | Mitigation |
|---|---|
| Upstream scrapers / schemas drift (yfinance, EDGAR) | Defensive lookups; missing fields become `None` claims with a stable shape; tools fail independently (`return_exceptions=True`); `scripts/smoke.py` checks drift. |
| LLM writes a wrong number or a wrong citation | Code computes comparisons; citations resolved and checked in code; rubric on every number; golden eval before prompt changes. |
| LLM cost overruns | Cache before rate limit, per-IP limit, a cheap production model, shared-secret gate. |
| Stale cached reports after a fix | `REPORT_VERSION`: a report cached before the current version rebuilds on its next visit. Report age and Regenerate cover the rest. |
| A card meets data it can't draw | Error boundary per card; unknown claim units parse as null. |
| Free-data sparsity | Per-section confidence, `fetched_at`, cards that hide when empty, and a line under the dashboard header naming the tools that found nothing. |
| A company moves to a new SEC registrant | The 10-Ks and XBRL history stay under the old one, with no link published; `sec_registrants.py` keeps the links by hand, and the empty-tool line is how a missing one gets noticed. |

## ADR index

- [ADR 0001](docs/adr/0001-stack-choice.md) — FastAPI + async SQLAlchemy + PostgreSQL
- [ADR 0002](docs/adr/0002-deployment.md) — Fly.io + Neon
- [ADR 0003](docs/adr/0003-pivot-equity-research.md) — Pivot to AI Equity Research Assistant
- [ADR 0004](docs/adr/0004-visual-first-product-shape.md) — Visual-first, delta-driven (no Morningstar narrative chase)
- [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md) — Symbol-centric dashboard with adaptive layouts
- [ADR 0006](docs/adr/0006-pluggable-llm-provider.md) — Switchable LLM provider (Anthropic / DeepSeek)
- [ADR 0007](docs/adr/0007-analytical-narratives.md) — Card prose that interprets; derived claims; analyst view; lenses

## Resume framing

What this project demonstrates, with backing in the codebase:

| Skill | Backed by |
|---|---|
| Production system design | Live Fly + Vercel + Neon deploy, RFC 7807 errors, observability, migrations on deploy, CI that boots the production image |
| Applied AI engineering | Single agent + tools, forced structured outputs, provider-switchable LLM layer, parallel calls, claim-id citations verified in code |
| Anti-hallucination engineering | Code-computed comparisons, citation-enforcing schema, programmatic confidence, factuality rubric over every number, live golden eval |
| Data visualization | Hand-rolled SVG charts with axes, baselines and hover; validated colorblind-safe palette for multi-series lenses; adaptive layouts |
| Cost-aware engineering | Free data + free-tier infra, cache-before-rate-limit, about a cent per fresh report |
| Test discipline | TDD on services, mocked providers, about 1,500 tests across backend and frontend, separate eval harness |
| Tradeoff articulation | ADRs 0001–0007 capture the why behind each pivot; dogfood logs show what changed and why |
