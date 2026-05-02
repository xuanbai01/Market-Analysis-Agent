# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [ADR 0003](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: on-demand structured reports, single agent + tools by default, free data only, citation discipline non-negotiable. Phase 1 infrastructure (FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, observability, tests, deploy pipeline) is complete and reused as-is.
>
> **Product shape:** [ADR 0004](../docs/adr/0004-visual-first-product-shape.md) — visual-first, delta-driven. Multi-year history rendered as charts; LLM commentary stays short and stays at genuinely judgment-dependent moments. **Not** chasing Morningstar-depth analyst narrative.

## In progress

- Phase 3 — Visual-first depth: schema (3.1) ✅ done; data-tool history (3.2.A–F) ✅ done; frontend visualization 3.3.A (Sparkline) ✅ + 3.3.B (SectionChart) ✅. **Up next:** 3.3.C (PeerScatter), then 3.5 (Vercel deploy + dogfood gate).

## Phase 3 — Visual-first depth (active)

> **Why this is Phase 3:** dogfooding the v1 report against several names surfaced a clear gap — point-in-time numbers without historical context feel shallow even when the underlying data is comprehensive. The fix isn't more LLM prose (per ADR 0003 anti-hallucination disciplines, prose stays short and citation-bound); the fix is multi-year history surfaced as charts. See [ADR 0004](../docs/adr/0004-visual-first-product-shape.md).
>
> **What this is NOT:** a chase of Morningstar-depth analyst narrative. No multi-year DCF projections, no fair-value estimates, no 5-page bull/bear essays. Those land (in attenuated form) in Phase 4, after the data foundation is right.
>
> **Frontend deploy status:** held until Phase 3 ships. PR #32 (frontend MVP) is merged on `main` and locally tested but not Vercel-deployed. The frontend will pick up history rendering as part of this phase rather than ship a deploy that immediately needs an upgrade.

### 3.1 Schema — `Claim.history` ✅ done (PR #35)

- [x] **`ClaimHistoryPoint`** — Pydantic model: `{period: str, value: float}`. `period` is a string (e.g. `"2024-Q4"`, `"2024-12"`, `"2024"`) — different tools emit different granularities; the rendering layer reads them as opaque labels. `value` is strictly numeric (`field_validator` rejects strings/bools — only floats sparkline).
- [x] **`Claim.history: list[ClaimHistoryPoint] = Field(default_factory=list)`** — added to `app/schemas/research.py`. Default empty so existing claims and existing cache rows round-trip unchanged. Ordered oldest-to-newest by convention; the renderer doesn't sort.
- [x] **Mirror in `frontend/src/lib/schemas.ts`** — Zod schema gets the same field with `.default([])`; existing reports parse unchanged.
- [x] **Round-trip test** — `Claim` with history → JSONB → read back → unchanged. Empty history round-trips as empty.

### 3.2 Tool extensions — Tier 1 (yfinance only, one PR per tool) ✅ done (PRs #36 → #40)

> **Concrete chart catalog** in [ADR 0004 §"Phase 3 — Concrete chart catalog"](../docs/adr/0004-visual-first-product-shape.md). Each PR below maps to one row in that catalog's Tier 1 table.

The pattern: each builder learns to populate `Claim.history` for the metrics where yfinance / FRED / derived computation gives us a series. Builders that can't (e.g. peer-comparison single-snapshot metrics) leave history empty.

- [x] **`fetch_fundamentals` history** (PRs #36 / #37 / #38 — sub-phases 3.2.A / B+C / D) — yfinance `Ticker.quarterly_financials`, `quarterly_balance_sheet`, `quarterly_cashflow` give ~5 years of quarters. 16 history-bearing claims now ship across:
    - **3.2.A** (PR #36): per-share growth (revenue, gross profit, op income, FCF, OCF) + margin trends (gross, operating, profit, FCF). 7 new claims, 2 existing claims gained history.
    - **3.2.B+C** (PR #37): cash flow components (CapEx, SBC per share) + balance sheet trend (cash + ST investments, total debt, total assets, total liabilities per share). 6 new claims.
    - **3.2.D** (PR #38): TTM ROE + TTM ROIC via 4Q rolling sum + flat 21% NOPAT tax rate. 1 new claim, ROE existing claim gained history.

    Provider returns `(values, history_map)` tuple; `_ratio_history` / `_ttm_sum` / `_nopat_series` helpers in `fundamentals_history.py`. Per-share denominator is `Diluted Average Shares` (per-quarter, not point-in-time `sharesOutstanding`). FCF reads yfinance's pre-computed row. `log_external_call` includes `history_populated_count` summary.
- [x] **`fetch_earnings` history** (PR #39, sub-phase 3.2.E) — refactored 21 q-prefixed keys (`q1.eps_actual` through `q4.eps_surprise_pct`) to 9 flat keys. 3 history-bearing claims (`eps_actual`, `eps_estimate`, `eps_surprise_pct`) carry up to 20 quarters via `Claim.history`. Switched from `Ticker.earnings_dates` property to `Ticker.get_earnings_dates(limit=24)` for ~6Y of depth. Surprise fallback when yfinance's column is missing.
- [x] **`fetch_macro` history** (PR #40, sub-phase 3.2.F) — provider returns `(snapshot, history_map)` matching fundamentals + earnings. FRED query: `frequency=m` + `limit=36` for ~3Y of monthly observations. Daily series (DGS10, DCOILWTICO, …) collapse to monthly server-side; already-monthly series (UMCSENT, MANEMP, RSAFS, UNRATE, CPIAUCSL) pass through unchanged. Snapshot/sparkline consistency preserved by construction (`<id>.value == history[-1].value`).
- [ ] **`fetch_valuation_history` (new derived tool)** — combines `fetch_fundamentals` history + price history into rolling P/E, EV/EBIT, EV/EBITDA, P/S over time, plus 5–10Y median band. Gives "AAPL trades at 28x today vs a 5Y median of 26x" — the most-cited gap from dogfooding. Pure compute; no new external call. *(Deferred — would unlock SectionChart for the Valuation section. Revisit after 3.5 dogfood.)*
- [ ] **`fetch_dividends_history` (new tool, conditional)** — yfinance `Ticker.dividends` for quarterly history; combined with price history for yield. Renders only when company is a dividend payer. Cheap to add since the source is one line. *(Deferred — would unlock the conditional `DividendsCard`. Revisit if dogfood signals it's missed.)*
- [ ] **Price-and-technicals history** — we already have OHLCV in `candles`; surface ~5y closing prices on a price-history claim, plus rolling SMA/RSI as charts. Reuse `app.services.technicals` rather than adding a new tool. *(Deferred — would unlock a price section / SectionChart variant. Revisit after 3.5 dogfood.)*
- [ ] **News in report** — wire `fetch_news` (already exists, currently unused in reports) into the orchestrator. Last ~10 symbol-filtered items as a Claim list with timestamps + URLs. Zero new acquisition cost. *(Deferred — Phase 4 catalyst-awareness work; news doesn't get a sparkline.)*
- [x] **Peers** stay as point-in-time (peer-comp gets a *visualization* upgrade in 3.3.C but not a history field — comparing 5y trends across 5 peers is a different chart shape, deferred).

### 3.3 Frontend visualization

- [x] **3.3.A — Sparkline + Trend column** (PR #41) — hand-rolled SVG (~30 lines) instead of Recharts for the inline use case (Recharts' ResponsiveContainer doesn't measure correctly in nested table cells / happy-dom). Default 80×24, slate-700 stroke, dot on the most-recent point, returns null when `history.length < 2`. ReportRenderer's claims table grew a "Trend" column hidden below `sm:` breakpoint. Recharts dep installed for 3.3.B; tree-shaken away from the 3.3.A bundle (75 KB gz, +0.5 KB net).
- [x] **3.3.B — `SectionChart` component** *(this PR)* — Recharts `LineChart` (300×120) at the top of sections with a featured-claim spec. **Lazy-loaded via `React.lazy()`** so recharts (~100 KB gz) lives in its own chunk, keeping the main bundle at 76 KB (under the 100 KB budget). `featured-claim.ts` picks per section title with exact-description matching:
    - Earnings → `Reported EPS (latest quarter)` (primary) + `Consensus EPS estimate (latest quarter, going in)` (secondary, dashed line)
    - Quality → `Return on equity` (single-line)
    - Capital Allocation → `Capital expenditure per share` (single-line)
    - Macro → first claim with description suffix `(latest observation)` and history (suffix predicate because Macro descriptions are dynamic per FRED series)
    - Valuation / Peers / Risk Factors / unknown title → skip (returns null)
    Y-axis ticks + tooltip reuse `formatClaimValue` (single source of truth with table cells AND backend eval rubric). Period axis uses `preserveStartEnd` to avoid 20Q label overlap.
- [ ] **3.3.C — `PeerScatter` component** — peer-comparison matrix as a 2-D scatter (P/E × gross margin). Subject highlighted vs peers. Augments the existing table (a11y: keep the table for screen readers). Includes `peer-grouping.ts` to regroup flat `peer_N.<metric>` claims into per-symbol records.
- [ ] **3.3.D *(deferred)* — multi-series / stacked enhancements:** CashFlowStacked (OCF / CapEx / SBC / FCF stacked bars), BalanceSheetTrend (cash vs debt overlay), multi-line Quality SectionChart (margins overlay), EarningsBeatRate (binary strip alongside EPS line). Land only if 3.5 dogfood signals these gaps.
- [ ] **`DividendsCard` component** *(deferred)* — quarterly dividends bar + yield line, dual-axis. Needs `fetch_dividends_history` tool first; both deferred together.
- [ ] **`NewsList` component** *(deferred to Phase 4)* — last ~10 items: source, title, timestamp, link out. Plain list; no sentiment shading. Needs `fetch_news` wired into orchestrator first.

### 3.4 Eval rubric extension

- [ ] **`_matches_claim` reads history** — when checking a number from prose against claim values, also check `claim.history[*].value`. A summary that says "EPS rose from 1.46 to 2.18" passes if both numbers appear anywhere in the referenced claim's history.
- [ ] **New golden case** with a history-bearing claim — verifies the rubric extension is exercised in CI, not just unit-tested.

### 3.5 Frontend deploy (after 3.1–3.4 land)

- [ ] **Vercel deploy** — push-to-deploy from `frontend/`. Set `VITE_BACKEND_URL`, set backend `FRONTEND_ORIGIN`, set `BACKEND_SHARED_SECRET` on both sides. README's "Deploying to Vercel" section already covers this.
- [ ] **Dogfood** the deployed stack against 5–10 real symbols. Note UX rough edges; fix the high-impact ones in a follow-up. **Decision gate for 3.6:** if the segment-level granularity (revenue / op income by reportable segment + by geography) is repeatedly missed during dogfooding, escalate to 3.6. If Tier 1 is enough, leave 3.6 deferred.
- [ ] **README + design_doc + CLAUDE.md** sweep — current state reflects Phase 3, screenshots, deploy URL.

### 3.6 Tool extensions — Tier 2 (EDGAR XBRL, conditional)

> **Conditional gate:** lands only if 3.5 dogfooding shows the segment view is still missed after Tier 1 ships. Tier 1 alone is the bulk of the perceived-shallowness fix; Tier 2 adds breadth where Tier 1 added depth.

- [ ] **XBRL parser** — pick `python-xbrl` or `arelle`; reuse `fetch_edgar`'s polite-crawl + disk-cache infrastructure. One-time effort; pays for itself across all SEC filers.
- [ ] **`fetch_segments` (new tool)** — parses `us-gaap:SegmentReportingDisclosure` from the latest 10-K + every 10-Q since. Returns revenue + operating income time series per reportable segment.
- [ ] **`fetch_geographic_revenue` (new tool)** — parses geographic-disaggregation tags. Returns revenue time series by region (US / Taiwan / China / etc., per the company's reporting structure — no normalization).
- [ ] **`fetch_rpo_history` (new tool, conditional)** — `us-gaap:RevenueRemainingPerformanceObligation` + `RemainingPerformanceObligationExpectedTimingOfSatisfactionPercentage` for the NTM%. Renders only when the company reports it (mostly SaaS / subscription / defense).
- [ ] **Frontend additions** — `SegmentDonut` (TTM share) + `SegmentTimeSeries` (per-segment trend chart), `GeographyDonut` + `GeographyTimeSeries`, `RPOCard` (conditional). Mirror profitviz's Tier 2 layouts; skip the polish.

## Phase 4 — Narrative layer (deferred; after Phase 3 ships)

> Phase 4 is intentionally deferred until Phase 3 ships and is dogfooded. With multi-year history in place, the LLM has trends to argue *from* — bull/bear cases become substantive instead of generic. Without Phase 3 first, Phase 4 is just longer-winded versions of today's summaries (per ADR 0004 §"Option 4 rejected").

- [ ] **Bulls Say / Bears Say** sections — explicit bullet lists with `claim_refs: list[str]` per argument so the rubric can enforce "every bullet cites at least one Claim." Schema work + LLM prompt work + rubric extension all required.
- [ ] **What Changed** section — surfaces quarter-over-quarter and year-over-year deltas mechanically (from Phase 3 history). LLM writes 1–2 sentence framing per delta.
- [ ] **Catalyst awareness** — wire `fetch_news` (already exists, not in reports today) and earnings dates into a "Coming up" / "Recent" framing. News claims need symbol-tagging upgrades for confidence (already partially done in `app.services.symbol_tagger`).
- [ ] **`?focus=thesis`** — new focus mode oriented around the bull/bear case for active investing decisions, complementing existing `full` (broad diligence) and `earnings` (event-driven).

## Cross-cutting (do alongside, not blocked on Phase 3)

- [ ] Turn on branch protection for `main` and add `ANTHROPIC_API_KEY` as a repo secret for the AI PR review job
- [ ] `.python-version` already pinned; verify it's respected by CI's uv setup
- [ ] **Set `ANTHROPIC_API_KEY` as a Fly secret** — needed before `/v1/research/*` works in prod: `fly secrets set 'ANTHROPIC_API_KEY=sk-ant-...'`
- [ ] **Local-dev CORS** — `.env.example` should recommend `FRONTEND_ORIGIN=http://localhost:5173` as the obvious local-dev value. Currently empty-by-default trips up every fresh-clone session that runs the frontend against the backend.

## Future scope (deliberately deferred — revisit when there's a concrete trigger)

- [ ] **`search_history`** — pgvector RAG over stored news + filings. Was the original "Phase 3" sketch in ADR 0003. Demoted by ADR 0004 because it doesn't address the perceived-shallowness gap. Revisit if a recurring eval query genuinely benefits from semantic search across our corpus.
- [ ] **`compute_options`** — yfinance options chain → IV percentile, implied move. Was the other half of the original "Phase 3" sketch. Demoted similarly. Revisit if Phase 4's Catalyst section needs implied-move framing.
- [ ] **LLM-driven section composition** (was 2.2d) — replace the static `SECTION_TO_CLAIM_KEYS` map with LLM triage. No signal yet that the deterministic catalog is too rigid.
- [ ] **Supervisor mode** (was 2.3) — multi-symbol comparative queries via specialist sub-agents. No signal that it adds factuality / structure benefit over the single-agent default.
- [ ] **Reddit / r/wallstreetbets sentiment** — narrow signal, high noise. Per ADR 0003 cut from must-have.
- [ ] **Discord bot client** — was original v1 vision; deferred indefinitely.
- [ ] **Real-time / 15-min scheduled ingest, Celery, Redis** — cut by ADR 0003.
- [ ] **Real auth + per-user cost caps + abuse logging** — only when there are real users. Phase 3.0's shared-secret gate is enough until then.

## Done

- [x] Phase 1 — Core Infrastructure
    - [x] Scaffold FastAPI app with v1 routers and RFC 7807 error handling
    - [x] Copy Claude Code harness (`CLAUDE.md`, docs, skills, agent, CI) from the project template
    - [x] Stand up tests/, async client + rollback-per-test DB fixtures, 12 endpoint tests
    - [x] Wire Alembic for schema migrations; baseline migration creates `symbols` + `news_items` + `candles`, seeds NVDA + SPY
    - [x] Real yfinance ingest with `ON CONFLICT DO UPDATE` upsert; provider-registry pattern
    - [x] `log_external_call` observability helper (A09 — service id, input/output summary, latency, timestamp, outcome)
    - [x] Replace fake bar in `market_repository` with real query against `candles`
    - [x] RSI + SMA20/50/200 in `technicals.py`; wired into `get_latest_snapshot`
    - [x] [ADR 0001](../docs/adr/0001-stack-choice.md) — FastAPI + async SQLAlchemy + PostgreSQL
    - [x] [ADR 0002](../docs/adr/0002-deployment.md) — Deploy to Fly.io, Postgres on Neon
    - [x] Fly.io + Neon deploy plumbing (`fly.toml`, GitHub Actions deploy workflow, runbook)
    - [x] Live deploy verified: `/v1/health` ✓, `/v1/symbols` ✓, `/v1/market/NVDA/ingest` returns 251 bars, technicals populate end-to-end
    - [x] [ADR 0003](../docs/adr/0003-pivot-equity-research.md) — Pivot to AI Equity Research Assistant

- [x] Phase 2 — v2 Equity Research Assistant
    - [x] **2.0 Foundations** — eval harness skeleton (`tests/evals/` + rubric + `GoldenCase`); citation-enforcing structured-output schema (`app/schemas/research.py`); LLM client + cost-tier routing (Haiku triage + Sonnet synth, both forced-schema, both `log_external_call`-wrapped, prompt caching on system blocks).
    - [x] **2.1 Tool registry** — 9/9 active tools shipped:
        - [x] `fetch_news` (PR #13) — NewsAPI dev tier + Yahoo per-ticker RSS, symbol tagging, `news_symbols` join
        - [x] `fetch_fundamentals` (PR #14) — yfinance valuation + quality + capital allocation + short interest + market cap
        - [x] `fetch_peers` (PR #15) — curated sector map + yfinance fallback, 4-metric peer matrix
        - [x] `fetch_edgar` (PR #17) — generic SEC filing fetcher with disk cache + polite-crawl
        - [x] `parse_filing` — `form_4` (PR #19), `13f` (PR #22), `10k_business` (PR #21), `10k_risks_diff`
        - [x] `fetch_earnings` (PR #18) — last 4Q EPS history + forward consensus + beat-rate (history extends in 3.2)
        - [x] `fetch_macro` (PR #20) — FRED with sector→series map (history extends in 3.2)
    - [x] **2.2 Agent + endpoint** — `POST /v1/research/{symbol}` (PR #26, deterministic-everything-except-prose); same-day cache (PR #28); per-IP rate limit (PR #29 + post-cache refinement). Real-LLM golden eval at factuality 0.97.

- [x] Phase 3.0 — Frontend backend prereqs (PR #31)
    - [x] **A1 — Shared-secret auth dep** (`app/core/auth.py::require_shared_secret`) — `Authorization: Bearer <BACKEND_SHARED_SECRET>` with `hmac.compare_digest`. No-op when secret is empty (default).
    - [x] **A2 — CORS middleware** (`app/core/cors.py::configure_cors`) — single-origin allowlist (never `*`), wired into `app/main.py` from `settings.FRONTEND_ORIGIN`.
    - [x] **A3 — `GET /v1/research`** list endpoint — paginated `ResearchReportSummary[]` for the dashboard sidebar; uses Postgres `->>` JSONB operator for cheap `overall_confidence` extraction.
    - 30 new tests; 426 passing in the full suite.

- [x] Phase 3.1 — Frontend MVP (PR #32) *(merged; deploy held pending Phase 3 visual-depth work per ADR 0004)*
    - [x] **`frontend/`** — Vite + React 18 + TS + Tailwind + TanStack Query + Zod
    - [x] **LoginScreen** with `probeAuth` against `GET /v1/research?limit=1`
    - [x] **Dashboard** with form, report renderer, past-reports sidebar, status-code-aware error banners
    - [x] **Vitest** smoke tests for Zod schemas + format helper + auth localStorage round-trip
    - [x] **`vercel.json`** + `frontend/README.md` deploy walkthrough
    - 19 vitest tests passing; production build 253 KB / 75 KB gzipped.

- [x] Phase 3.1 schema — `Claim.history` (PR #35)
    - [x] `ClaimHistoryPoint(period: str, value: float)` — Pydantic frozen model + Zod mirror
    - [x] `Claim.history: list[ClaimHistoryPoint] = Field(default_factory=list)` — backwards-compat default
    - [x] Field validator rejects str/bool on `value` (only floats sparkline)
    - [x] JSONB round-trip test confirms cached pre-3.1 rows still parse

- [x] Phase 3.2 — Tool history (PRs #36 → #40)
    - [x] **3.2.A** (PR #36) — `fetch_fundamentals` per-share growth + margin trends (7 new claims, 2 existing get history)
    - [x] **3.2.B+C** (PR #37) — cash flow components + balance sheet trend (6 new claims)
    - [x] **3.2.D** (PR #38) — TTM ROE + ROIC via 4Q rolling sum + flat 21% NOPAT tax rate (1 new claim, ROE gets history)
    - [x] **3.2.E** (PR #39) — `fetch_earnings` 21 q-prefixed keys → 9 flat keys with 20Q lookback via `get_earnings_dates(limit=24)`
    - [x] **3.2.F** (PR #40) — `fetch_macro` ~36 monthly observations per FRED series via `frequency=m`; provider tuple shape converged across all three multi-period tools
    - **Net result:** 19+ history-bearing claims, all snapshot/`history[-1]` consistent by construction. 499/499 backend tests pass.

- [x] Phase 3.3.A — Sparkline + Trend column (PR #41)
    - [x] Hand-rolled SVG `Sparkline` component (~30 lines, no Recharts for inline use)
    - [x] ReportRenderer "Trend" column added; hidden below `sm:` breakpoint
    - [x] `recharts ^2.13` installed (used by 3.3.B); tree-shaken away from 3.3.A bundle
    - [x] 40/40 frontend tests pass (was 19; +21 new). Bundle 75 KB gz (+0.5 KB).

- [x] Phase 3.3.B — SectionChart *(this branch)*
    - [x] `featured-claim.ts` picker — exact-description match per section title; macro suffix predicate; null-guards for unknown / sparse / pre-3.2 cached reports
    - [x] Recharts `LineChart` SectionChart component — 300×120 default, slate-700 primary + dashed slate-400 secondary, reuses `formatClaimValue` for ticks/tooltip
    - [x] Lazy-loaded via `React.lazy()` so recharts splits into its own chunk; main bundle 76 KB gz (under 100 KB budget); SectionChart chunk 103 KB gz on-demand
    - [x] 67/67 frontend tests pass (was 40; +15 featured-claim + 8 SectionChart + 4 ReportRenderer wiring)

## Blocked / waiting

-
