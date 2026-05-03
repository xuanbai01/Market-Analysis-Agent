# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

> **Product context:** this repo is the **AI Equity Research Assistant** — a FastAPI backend exposing `POST /v1/research/{symbol}` that returns a Pydantic-typed citation-backed research payload, plus a React + Vite frontend rendering it as a **symbol-centric dashboard at `/symbol/:ticker`** (Phase 4, in progress). Single agent + well-designed tools, free data only, citation discipline non-negotiable. **Visual-first, delta-driven** product shape (charts > prose), with **adaptive layouts** for distressed names. The original v1 vision (real-time multi-agent platform, Discord bot) was cut by [ADR 0003](docs/adr/0003-pivot-equity-research.md); the visual-first commitment (no Morningstar-narrative chase) is in [ADR 0004](docs/adr/0004-visual-first-product-shape.md); the pivot from generated-report-page to symbol-centric-dashboard is in [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md).
>
> **System design:** [`design_doc.md`](design_doc.md) (root) is the source of truth for scope, budget, stack, and roadmap. Read it before making non-trivial changes.
> **Active tasks:** `tasks/todo.md`. Lessons: `tasks/lessons.md`.
> **Architecture Decision Records:** `docs/adr/` — **read [ADR 0003](docs/adr/0003-pivot-equity-research.md), [ADR 0004](docs/adr/0004-visual-first-product-shape.md), and [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md) before proposing surface-shape changes.**

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
- **Phase 3.3 done (frontend visualization):** 3.3.A (PR #41), 3.3.B (PR #42), 3.3.C (PR #43) all merged. `Sparkline` + Trend column, `SectionChart` for Earnings / Quality / Capital Allocation / Macro, `PeerScatter` for the Peers section. Main bundle 76.92 KB gz; recharts hoisted into a shared 100 KB chunk used by both lazy chart components.
- **Phase 3.4 done (eval rubric history) (PR #44):** `_claim_numeric_values` widens to yield each `Claim.history[*].value` so trend prose like "EPS rose from 1.40 to 2.18" matches even when the endpoints aren't the snapshot.
- **Phase 4 active (symbol-centric dashboard rebuild):** Per [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md). 8–10 weeks across 4.0–4.8.
  - **4.0 done (PR #46):** Strata token system, Inter + JetBrains Mono, `react-router-dom@6`, `SidebarShell`, `RequireAuth`, `LandingPage`, `SymbolDetailPage`, dark-theme restyle of existing components.
  - **4.1 done (PR #47):** Real `HeroCard` (3-column, price chart + featured stats + meta) + `EarningsCard` (20Q EPS bars + beat-rate headline) + new `LineChart` and `EpsBars` SVG primitives. Backend: `GET /v1/market/:ticker/prices?range={60D,1Y,5Y}` with read-through `candles` cache; `fetch_fundamentals` adds `name`/`sector_tag`/`fifty_two_week_high`/`fifty_two_week_low`; orchestrator lifts `name`/`sector` to `ResearchReport` top-level.
  - **4.2 done (PR #48):** `QualityCard` (3 metric rings ROE/ROIC/FCF + multi-line gross/op/FCF margin chart + hybrid 6+expand to 16 claims) + `ValuationCard` (4-cell matrix P/E TTM / P/E FWD / P/S / EV/EBITDA with peer-percentile bars) + `PeerScatterV2` (hand-rolled SVG, 3 axis presets — replaces 3.3.C Recharts version). New SVG primitives `MetricRing` + `MultiLine`; new extractors `quality-extract.ts` + `valuation-extract.ts`; `peer-grouping.ts` extended with axis-pair-generic helpers.
  - **4.3.A done:** `PerShareGrowthCard` (5 per-share series rebased first=100, MultiLine + 5 growth-multiplier pills) + `CashAndCapitalCard` (cross-section: CapEx/SBC + Cash/Debt MultiLine + Net cash highlight) + `RiskDiffCard` (inline 4-row horizontal-bar SVG of added/removed/kept/char-delta + prose framing "expanded/shrank/stable") + `MacroPanel` (vertical stack of mini area-chart panels, one per FRED series). New extractors `growth-extract.ts` + `cash-capital-extract.ts` + `risk-extract.ts` + `macro-extract.ts`. All-frontend; backend untouched. Main bundle 92.93 KB gz (+2.7). 522/522 backend + 262/262 frontend tests.
  - **4.3.B deferred follow-up:** Haiku-driven per-category risk categorizer + RiskDiffCard upgrade to per-category bars.
  - **4.4 next:** News integration + Business descriptions + section narratives.
  - 4.5–4.7 follow per `tasks/todo.md`. 4.8 = Vercel deploy + dogfood gate.
- **Phase 5 deferred (narrative layer):** Bulls Say / Bears Say with `claim_refs`, What Changed, `?focus=thesis`. Lands only if Phase 4.8 dogfooding shows the dashboard's inline narratives don't satisfy the bull/bear-case need.
- **Phase 6 deferred (XBRL Tier 2):** segment + geography revenue breakdowns, RPO. Conditional on Phase 4.8 signal.
- **Indefinitely deferred** per ADR 0004: `search_history` (pgvector RAG), `compute_options` (yfinance + IV snapshots), Reddit sentiment, real auth + per-user cost caps.

**Tables today:** `symbols`, `news_items`, `news_symbols`, `candles`, `research_reports`. pgvector + `embeddings` columns are not added until/unless `search_history` un-defers.

**Stubs / 501s:** `/v1/analysis`, `/v1/reports/daily/latest`, `/v1/forecasts/{symbol}` are legacy v1 routes — they'll be removed or redirected to `/v1/research` when convenient. Don't fill them in; prefer adding to `/v1/research`'s shape via the Phase 4 roadmap.

**Phase 4 backend additions** (lands alongside frontend work):
- `GET /v1/market/:ticker/prices?range=60D` — OHLCV from `candles` for the hero price chart (data exists, just no route)
- News integration in orchestrator (`fetch_news` tool exists from PR #13, just not wired)
- Logo URL resolution (Clearbit or static map)
- Layout signals payload (`is_unprofitable_ttm`, `cash_runway_quarters`, etc. — derived from existing claims)

When making changes, prefer extending the existing shape (new claims, new history fields, new sections in the static `SECTION_TO_CLAIM_KEYS` registry) over adding parallel surfaces. The deterministic-everything-except-prose architecture is the discipline — read [`app/services/research_orchestrator.py`](app/services/research_orchestrator.py) before proposing structural changes.
