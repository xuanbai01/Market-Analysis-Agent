# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

> **Product context:** this repo is the **AI Equity Research Assistant** — a FastAPI backend exposing `POST /v1/research/{symbol}` that returns a Pydantic-typed citation-backed research report, plus a React + Vite frontend that renders it. Single agent + well-designed tools, free data only, citation discipline non-negotiable. **Visual-first, delta-driven** product shape (charts > prose). The original v1 vision (real-time multi-agent platform, Discord bot) was cut by [ADR 0003](docs/adr/0003-pivot-equity-research.md); the report-shape decision (no Morningstar-narrative chase) is in [ADR 0004](docs/adr/0004-visual-first-product-shape.md).
>
> **System design:** [`design_doc.md`](design_doc.md) (root) is the source of truth for scope, budget, stack, and roadmap. Read it before making non-trivial changes.
> **Active tasks:** `tasks/todo.md`. Lessons: `tasks/lessons.md`.
> **Architecture Decision Records:** `docs/adr/` — **read [ADR 0003](docs/adr/0003-pivot-equity-research.md) and [ADR 0004](docs/adr/0004-visual-first-product-shape.md) before proposing report-shape changes.**

## How this file works

The `@imports` below pull in modular docs — one concern per file — so a single CLAUDE.md does not balloon. Keep this file short; edit the imported docs instead.

---

@docs/commands.md

@docs/architecture.md

@docs/conventions.md

@docs/testing.md

@docs/security.md

@docs/workflow.md

---

## Current state

- **Phase 1 done:** FastAPI scaffold, async SQLAlchemy 2.0 + asyncpg, Alembic, real yfinance ingest, RSI/SMA technicals, RFC 7807 errors, A09 external-call logging, Fly.io + Neon deploy, push-to-deploy via GitHub Actions.
- **Phase 2 done:** `POST /v1/research/{symbol}` is the primary endpoint. Citation-enforcing schema (`Source` / `Claim` / `Section` / `ResearchReport`). 9 free-data tools (`fetch_news`, `fetch_fundamentals`, `fetch_peers`, `fetch_edgar`, `parse_filing` × 4, `fetch_earnings`, `fetch_macro`). Cost-tier-routed LLM client (Haiku triage + Sonnet synth, currently synth-only). Same-day cache (default 7-day window). Per-IP rate limit (default 3/hour, post-cache). Real-LLM golden eval at factuality 0.97.
- **Phase 3.0 done (PR #31):** shared-secret bearer auth dep on `/v1/research/*` (`BACKEND_SHARED_SECRET`), CORS middleware (`FRONTEND_ORIGIN`), `GET /v1/research` paginated list.
- **Phase 3.1 done (PR #32; deploy held):** React + Vite + TS frontend under `frontend/`. Login screen, dashboard, report renderer, past-reports sidebar. Vercel deploy held until Phase 3 visual-depth ships.
- **Phase 3.1 schema done (PR #35):** `Claim.history: list[ClaimHistoryPoint]` added to Pydantic + Zod. Backwards-compat default `[]` so pre-3.1 cached rows round-trip unchanged.
- **Phase 3.2 done (PRs #36 → #40):** all four data-tool history extensions shipped. `fetch_fundamentals` ships 16 history-bearing claims (per-share growth, margin trends, cash flow components, balance sheet trend, ROE/ROIC TTM); `fetch_earnings` ships 3 history-bearing claims with ~20Q lookback; `fetch_macro` ships per-series histories with ~36 monthly observations via FRED `frequency=m`. All three providers converged on a `(values, history_map)` tuple shape.
- **Phase 3.3 active (frontend visualization):** 3.3.A done (PR #41) — `Sparkline` (custom 30-line SVG) + Trend column in claims table. 3.3.B done — `SectionChart` (Recharts LineChart, lazy-loaded so the main bundle stays under 100 KB gz; recharts split into its own ~100 KB chunk) at the top of Earnings / Quality / Capital Allocation / Macro sections; `featured-claim.ts` picks primary+secondary via exact description match. Main bundle 76 KB gz; SectionChart chunk 103 KB gz on-demand. 3.3.C (`PeerScatter`) follows.
- **Phase 4 deferred:** narrative layer (Bulls / Bears with `claim_refs`, What Changed, catalyst awareness). Lands only after Phase 3 dogfooding.
- **Indefinitely deferred** per ADR 0004: `search_history` (pgvector RAG), `compute_options` (yfinance + IV snapshots), Reddit sentiment, real auth + per-user cost caps. None address the perceived-shallowness gap; revisit when there's a concrete trigger.

**Tables today:** `symbols`, `news_items`, `news_symbols`, `candles`, `research_reports`. pgvector + `embeddings` columns are not added until/unless `search_history` un-defers.

**Stubs / 501s:** `/v1/analysis`, `/v1/reports/daily/latest`, `/v1/forecasts/{symbol}` are legacy v1 routes — they'll be removed or redirected to `/v1/research` when convenient. Don't fill them in; prefer adding to `/v1/research`'s shape via the Phase 3/4 roadmap.

When making changes, prefer extending the existing shape (new claims, new history fields, new sections in the static `SECTION_TO_CLAIM_KEYS` registry) over adding parallel surfaces. The deterministic-everything-except-prose architecture is the discipline — read [`app/services/research_orchestrator.py`](app/services/research_orchestrator.py) before proposing structural changes.
