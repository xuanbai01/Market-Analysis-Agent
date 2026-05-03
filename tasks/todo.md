# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [ADR 0003](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: free data only, citation discipline non-negotiable. Phase 1 infrastructure complete.
>
> **Product shape:** [ADR 0004](../docs/adr/0004-visual-first-product-shape.md) — visual-first, delta-driven. Multi-year history rendered as charts; LLM commentary stays short. **Not** chasing Morningstar-depth analyst narrative.
>
> **Surface shape:** [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md) — pivot from "click Generate → static report" to **symbol-centric dashboard** (`/symbol/:ticker`) with adaptive layouts. Same backend; new frontend architecture.

## In progress

- **Phase 4 — Symbol-centric dashboard rebuild** (Strata design from user's prototyping session). Backend stays mostly intact; frontend rebuilt as `/symbol/:ticker` route with sidebar shell, hero card, grid-laid-out cards, and adaptive layouts for distressed names. **Up next:** 4.0 (token system + sidebar shell + route refactor). See [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md).

## Phase 4 — Symbol-centric dashboard (active)

> **Why this is Phase 4:** dogfooding the Phase 3 visual depth (sparklines, section charts, peer scatter) against MSFT / NVDA / AMZN / AAPL / RIVN locally surfaced that the *data and visualization were right* but the *container was wrong*. "Click Generate → scroll a static report" feels like a generated artifact, not a tool. profitviz / stockanalysis / finchat all converge on a symbol-centric dashboard for a reason. See [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md) for the full reasoning.
>
> **What this is NOT:** a polish task. The Strata design pivot is structural — adaptive layouts (RIVN reframes to cash runway / burn / risk; healthy names show valuation + quality + growth), bookmarkable URLs, sidebar persistence, and Compare mode are all impossible in the report shape regardless of how much polish we apply.
>
> **Phase 3 status:** schema (3.1) ✅; data-tool history (3.2.A–F) ✅; frontend visualization (3.3.A–C) ✅; eval rubric history (3.4) ✅. All survives. The frontend visualizations get partially deprecated — `Sparkline` and the chart helpers live on; `SectionChart` / `PeerScatter` / `ReportRenderer` get replaced by Strata variants. The `/v1/research/{symbol}` endpoint and same-day cache layer stay; the renderer that consumes them is what changes.
>
> **Vercel deploy:** moved from Phase 3.5 to Phase 4.8. Holding the deploy until the new UI lands rather than shipping a public deploy that immediately needs a redesign.

### 4.0 Token system + sidebar shell + route refactor

- [ ] **`tokens.css`** — slate base (9-step), 9 semantic accents (Valuation cyan / Quality mint / Growth yellow-green / Cash flow amber / Balance orange / Earnings rose / Peers violet / Macro slate-blue / Risk coral) at constant chroma + lightness, state colors (pos/neg/neutral/highlight), typography scale (Inter + JetBrains Mono), spacing rhythm (4/8/12/16/24/32/48/64), 4-step radii. Tailwind config maps these to utility classes.
- [ ] **`SidebarShell`** — 72px fixed-width left rail with logo, Search (`⌘K`), Compare, Watchlist, Recent, Export. Active-state via accent tint + border. Persistent across all routes.
- [ ] **Route refactor** — replace form-driven `/` with router. Routes: `/` (landing — search + recent), `/symbol/:ticker` (dashboard), `/login`. `/compare?a=X&b=Y` lands in 4.6.
- [ ] **`SearchModal`** — `⌘K` global keyboard hook. Ticker autocomplete from a static curated list initially; later `/v1/symbols` autocomplete endpoint.
- [ ] **`SymbolDetailPage` skeleton** — empty grid layout that renders chrome (header, footer with cached-time + source attribution) and placeholder cards. Becomes real in 4.1+.
- [ ] **Backend: `/v1/market/:ticker/prices?range=60D`** — surface OHLCV from `candles` for the hero price chart. Default ranges: 1D / 5D / 1M / 3M / 1Y / 5Y. JSON shape: `{period, prices: [{ts, close, volume}]}`.
- [ ] **Backend: logo URL resolution** — Clearbit (`logo.clearbit.com/<domain>`) with a static map for the top ~50 names; null fallback for the rest. Cheap addition to `fetch_fundamentals`.

### 4.1 Hero card + Earnings card

- [ ] **`HeroCard`** — full-width, glow-shadow. Three columns: ticker meta (logo, NVDA, NASDAQ, sector tag, name, big price, delta, MCAP/VOL/52W meta) | 60-day price chart with 1D/5D/1M/3M/1Y/5Y range pills | three featured stats (Forward P/E, ROIC TTM, FCF Margin) with peer/historical sub-context.
- [ ] **`EarningsCard`** — 20-quarter EPS bars (actual vs estimate, color-coded beat/miss), "X of 20 beat consensus" headline, next-print date with after-market tag, three stats below (beat rate, surprise μ, EPS TTM).
- [ ] **`LineChart` primitive** — hand-rolled SVG with optional area fill, configurable stroke width and color. Replaces Recharts `LineChart` for the hero use case.
- [ ] **`EpsBars` primitive** — 20-bar chart with conditional coloring (green for beat, red for miss). Hand-rolled SVG.
- [ ] **Visible after 4.1:** any ticker URL renders a real hero region with price chart + 3 KPIs + 20Q earnings history. Compelling first-paint product moment even before the rest of the cards land.

### 4.2 Quality scorecard + Valuation matrix + PeerScatter v2

- [ ] **`QualityScorecard`** — 3 metric rings (ROE / ROIC / FCF margin) at top, multi-line margin chart (gross / operating / FCF) below, hybrid 6+expand: default shows the 6 most-important Quality claims, "Show all 16" disclosure expands to the full set. Compact density auto-collapses to 6.
- [ ] **`MetricRing` primitive** — circular ring with center value + label below + sub-label. Hand-rolled SVG.
- [ ] **`MultiLine` primitive** — 2-4 series on a shared axis with x-labels + grid. Hand-rolled SVG. Replaces Recharts `LineChart` for the multi-series use case.
- [ ] **`ValuationMatrix`** — 4-cell grid (P/E trailing, P/E forward, P/S, EV/EBITDA) each with peer median + percentile bar showing where subject sits in peer distribution. Below the grid: PeerScatter v2.
- [ ] **`PeerScatter` v2** — hand-rolled SVG (replaces 3.3.C Recharts ScatterChart). Selectable axes via dropdown: P/E × Gross Margin (default), P/S × Operating Margin, EV/EBITDA × ROIC. Subject highlighted as larger labeled dot; peers as smaller dots; median as a cross. X/Y axis labels visible.

### 4.3 Per-share growth + Cash & capital + Risk diff + Macro

- [ ] **`PerShareGrowth`** — 5Y per-share series (revenue, gross profit, op income, FCF) rebased to Q1 of period start = 100. Multi-line chart shows true relative growth on shared axis. Below: 5 growth-multiple pills (Rev × N, GP × N, OpI × N, FCF × N, OCF × N).
- [ ] **`CashAndCapital`** — dual stack: top is CapEx + SBC per-share lines, bottom is Cash + Debt per-share lines. Highlight box at the bottom: Net cash / share. Compact: stacks vertically; comfortable: side-by-side.
- [ ] **`RiskDiff`** — bar chart of paragraph-count deltas by risk category (AI/regulatory, Export controls, Supply concentration, Customer concentration, Competition, Cybersecurity, IP, Macro). One-sentence prose summary below ("Disclosure expanded. Net +9 ¶ across categories — concentrated in AI/regulatory and export controls"). Backend addition: extend `extract_10k_risks_diff` to bucket added/removed paragraphs by category via Haiku classification.
- [ ] **`MacroPanel`** — 1-2 stacked mini-area-charts (CPI YoY, US 10Y rate) with current value badges. One-sentence prose summary below ("Disinflation continues; 10Y has compressed 43 bps from peak — modest tailwind for long-duration multiples").

### 4.4 News + Business + section narratives

- [ ] **News integration** — wire `fetch_news` (already exists, PR #13) into the orchestrator's tool fan-out. New `_build_news` section builder. Last ~30 ranked items. Yahoo per-ticker RSS (free, no auth) is the primary source; NewsAPI free tier (100/day) augments.
- [ ] **Haiku news categorization** — for each headline, classify category (EARNINGS / PRODUCT / REGULATORY / M&A / SUPPLY / STRATEGY / OTHER) + sentiment (positive / neutral / negative). Haiku 4.5 at ~$0.0001 per headline; ~$0.003 per report total.
- [ ] **`NewsList` component** — last 5 ranked items by default, with category pills (filter ALL / EARNINGS / PRODUCT / REGULATORY / M&A / SUPPLY) and sentiment counts in footer. "View N more" expands.
- [ ] **Business description** — yfinance `Ticker.info["longBusinessSummary"]` surfaced as a 1-paragraph card. Founded year, HQ, employee count from `info` too.
- [ ] **`ContextBand`** — top of `SymbolDetailPage` (between hero and grid), holds Business description card + News card + (later) Revenue mix segment + geography + Next Catalyst. Layout: 2-column on comfortable, 1-column on compact.
- [ ] **Section narratives** — Sonnet generates 1-2 sentence inline interpretations per card ("Loss is narrowing. EPS −3.82 → −0.78 over 20Q — no positive print"). Renders in the card's bottom strip, below the data. Backed by Claim refs same as section summaries.
- [ ] **Eval rubric** — section narratives covered by the same factuality rubric (already history-aware after 3.4).

### 4.5 Adaptive layout for distressed names *(the differentiator)*

- [ ] **Backend signals** — extend `compose_research_report` to compute layout flags from claim values: `is_unprofitable_ttm`, `beat_rate_below_30pct`, `cash_runway_quarters` (derived from net cash / FCF burn TTM), `gross_margin_negative`, `debt_rising_cash_falling`. Payload field `layout_signals: dict[str, bool | float]`.
- [ ] **Layout substitution rules** — when `is_unprofitable_ttm`: hero swaps Forward P/E → P/Sales, ROIC → Cash Runway, FCF Margin stays but with red coloring. When `beat_rate_below_30pct`: Earnings card adds "bottom decile" annotation. When `cash_runway_quarters < 6`: Cash & Capital card adds "raise likely needed" annotation + runway highlight.
- [ ] **Header pills** — "● UNPROFITABLE · TTM" and "⚠ LIQUIDITY WATCH" pills in the page header for distressed names; nothing for healthy names.
- [ ] **Section ordering changes** — for distressed names, Cash & Capital moves up (above Per-share growth); Risk diff moves up (above Macro). Layout flags drive the section order.
- [ ] **Narratives adapt** — section narratives reference the distressed framing ("Trajectory positive, level negative. Gross margin up 226 pts in 5Y but still below break-even"). Sonnet prompts include the layout signals as context.
- [ ] **Test fixtures** — at least 4 fixture symbols covering the matrix: healthy mature (NVDA, AAPL), slowing growth (F, GM), unprofitable growth (RIVN, LCID), distressed (any name with runway < 4Q at the time of writing).

### 4.6 Compare page

- [ ] **`/compare?a=NVDA&b=AVGO`** route — two-ticker side-by-side dashboard.
- [ ] **`CompareHero`** — two ticker cards side-by-side with mini price charts in the subject's accent color (NVDA cyan, AVGO violet say). "VS" indicator between them.
- [ ] **Valuation comparison** — 4 metrics (P/E forward, P/S, EV/EBITDA, PEG) shown as horizontal bars between the two values with "lower = cheaper" hint.
- [ ] **Quality comparison** — 4 metrics (Gross margin, Operating margin, FCF margin, ROIC) with horizontal bars.
- [ ] **Overlay charts** — 20Q operating margin, 5Y per-share growth (both rebased) with both tickers on shared axes. Narrative call-out below each chart ("NVDA's operating margin overtook AVGO's in Q2-23. AVGO is the steadier business; NVDA captured the cycle").
- [ ] **Risk diff side-by-side** — both tickers' 10-K risk paragraph deltas as parallel bar charts.
- [ ] **"What's cut" footer** — explicitly lists what doesn't appear in compare mode (Macro, full Business descriptions, News). Honest about scope.
- [ ] **Add ticker / Swap controls** — top-right.

### 4.7 Search + Watchlist + Recent

- [ ] **Search modal** (`⌘K`) — full ticker search; landed in skeleton form in 4.0, fully functional here. Recent + watchlist surfaced inline.
- [ ] **Watchlist** — localStorage-backed list of tickers; sidebar Watch icon shows live count badge. Clicking a watchlist entry navigates to `/symbol/:ticker`.
- [ ] **Recent ticker tracking** — last ~10 visited tickers stored in localStorage. Surfaced in sidebar Recent panel + landing page.
- [ ] **Landing page (`/`)** — search bar, recent tickers as cards (with mini price sparklines), watchlist as a second section, "What's new" feed pulling from `fetch_news` (sector-level instead of per-ticker).

### 4.8 Vercel deploy + dogfood gate

- [ ] **Vercel push-to-deploy** from `frontend/`. Set `VITE_BACKEND_URL`, set backend `FRONTEND_ORIGIN`, set `BACKEND_SHARED_SECRET` on both sides.
- [ ] **Backend env-var hardening** — confirm Fly secrets match the new dashboard's needs (`ANTHROPIC_API_KEY`, `NEWSAPI_KEY`, `FRED_API_KEY`, `BACKEND_SHARED_SECRET`).
- [ ] **Dogfood** the deployed stack against 8–10 real symbols spanning the layout matrix (healthy mega-cap, growth, distressed, dividend payer, cyclical). Note rough edges.
- [ ] **Decision gate for Phase 5 vs Phase 6:** if dogfooding surfaces "I want a real bull/bear case" repeatedly, escalate to Phase 5 (narrative layer). If it surfaces "I need segment / geography breakdowns", escalate to Phase 6 (XBRL Tier 2). If neither dominates, the dashboard is the product and remaining work is polish.
- [ ] **README + design_doc + CLAUDE.md** sweep — current state reflects Phase 4, screenshots, deploy URL. Update portfolio framing too.

## Phase 5 — Narrative layer (deferred; after Phase 4 dogfooding)

> **Deferred** until Phase 4 ships and is dogfooded. The dashboard's adaptive layout for distressed names (Phase 4.5) plus inline section narratives (Phase 4.4) already deliver a meaningful slice of "what would Bulls Say / Bears Say articulate?" — the killer questions ("EPS narrowing toward break-even but cash runway tightening" or "Operating margin expansion outpacing peers") get answered by the dashboard's data presentation. Phase 5 lands only if dogfooding surfaces a recurring "I want a real bull/bear case" signal that the inline narratives don't satisfy.

- [ ] **Bulls Say / Bears Say** sections — explicit bullet lists with `claim_refs: list[str]` per argument so the rubric can enforce "every bullet cites at least one Claim." Schema work + LLM prompt work + rubric extension all required.
- [ ] **What Changed** section — surfaces quarter-over-quarter and year-over-year deltas mechanically (from Phase 3 history). LLM writes 1–2 sentence framing per delta. Some of this already exists implicitly in Phase 4.5 adaptive narratives.
- [ ] **Catalyst awareness** — already partially in Phase 4.4 (next-print date + recent news with sentiment). Phase 5 expansion would tie news directly to the bull/bear thesis ("Q3 print added +7 ¶ to risk factors — feeds the bear case below").
- [ ] **`?focus=thesis`** — new focus mode oriented around the bull/bear case for active investing decisions, complementing existing `full` (broad diligence) and `earnings` (event-driven).

## Phase 6 — XBRL Tier 2 (deferred; conditional on Phase 4.8 dogfood signal)

> **Deferred** until Phase 4.8 dogfooding shows the segment / geography / RPO breakdowns are repeatedly missed. The Phase 4 dashboard has placeholder cards in the context band for "Revenue mix by segment" and "Revenue mix by geography" that render "data not available" until this lands. If users repeatedly note the gap (especially for names where segment mix is the story — NVDA Data Center vs Gaming, AMZN AWS vs Retail), escalate.

- [ ] **XBRL parser** — pick `python-xbrl` or `arelle`; reuse `fetch_edgar`'s polite-crawl + disk-cache infrastructure. One-time effort; pays for itself across all SEC filers.
- [ ] **`fetch_segments` (new tool)** — parses `us-gaap:SegmentReportingDisclosure` from the latest 10-K + every 10-Q since. Returns revenue + operating income time series per reportable segment.
- [ ] **`fetch_geographic_revenue` (new tool)** — parses geographic-disaggregation tags. Returns revenue time series by region (US / Taiwan / China / etc., per the company's reporting structure — no normalization).
- [ ] **`fetch_rpo_history` (new tool, conditional)** — `us-gaap:RevenueRemainingPerformanceObligation` + `RemainingPerformanceObligationExpectedTimingOfSatisfactionPercentage` for the NTM%. Renders only when the company reports it (mostly SaaS / subscription / defense).
- [ ] **Frontend additions** — `SegmentDonut` (TTM share) + `SegmentTimeSeries` + `GeographyDonut` + `GeographyTimeSeries` + `RPOCard` rendered into the Phase 4.4 ContextBand placeholders.

## Other deferred Phase 3 work (rolled forward; revisit case-by-case)

These were sketched during Phase 3 but never landed; either Phase 4 absorbs them (news, price history) or they stay deferred:

- [x] **News in report** — absorbed into Phase 4.4 (NewsList component + Haiku categorization).
- [ ] **`fetch_valuation_history` (new derived tool)** — rolling P/E / EV/EBIT / EV/EBITDA over time with median bands. Would unlock a SectionChart for Valuation. *(Still deferred — Phase 4.2's Valuation matrix uses point-in-time + peer percentile bars instead. Revisit if Phase 4.8 dogfooding shows users want "trades at 28× vs 5Y median 26×" framing.)*
- [ ] **`fetch_dividends_history` (new tool, conditional)** — yfinance `Ticker.dividends` for quarterly history; would unlock a `DividendsCard`. *(Still deferred — niche to dividend payers. Revisit if a recurring use case surfaces.)*
- [ ] **Price-and-technicals history** — partially absorbed into Phase 4.0/4.1 (60-day price chart in hero). Full SMA / RSI overlay and 5Y price view still TBD; revisit if Phase 4.8 dogfooding shows demand.

## Cross-cutting (do alongside, not blocked on Phase 4)

- [ ] Turn on branch protection for `main` and add `ANTHROPIC_API_KEY` as a repo secret for the AI PR review job
- [ ] `.python-version` already pinned; verify it's respected by CI's uv setup
- [ ] **Set `ANTHROPIC_API_KEY` as a Fly secret** — needed before `/v1/research/*` works in prod: `fly secrets set 'ANTHROPIC_API_KEY=sk-ant-...'`
- [ ] **Local-dev defaults sweep** — write a `LOCAL_DEV.md` in the repo root capturing the Phase 3 dogfood lessons: (1) `.env` `DATABASE_URL` should default to local Docker (`postgresql+asyncpg://postgres:postgres@localhost:5432/marketdb`) not Neon; (2) Windows users with native Postgres on :5432 need to either stop the service or remap docker to :5433; (3) `RESEARCH_CACHE_MAX_AGE_HOURS=0` disables cache for debug; (4) browser extensions can rewrite responses — test in incognito to isolate.
- [ ] **`.env.example`** — recommend `FRONTEND_ORIGIN=http://localhost:5173` as the obvious local-dev value (currently empty trips up fresh-clone sessions).

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

- [x] Phase 3.3.B — SectionChart (PR #42)
    - [x] `featured-claim.ts` picker — exact-description match per section title; macro suffix predicate; null-guards for unknown / sparse / pre-3.2 cached reports
    - [x] Recharts `LineChart` SectionChart component — 300×120 default, slate-700 primary + dashed slate-400 secondary, reuses `formatClaimValue` for ticks/tooltip
    - [x] Lazy-loaded via `React.lazy()` so recharts splits into its own chunk; main bundle 76 KB gz (under 100 KB budget); SectionChart chunk 103 KB gz on-demand
    - [x] 67/67 frontend tests pass (was 40; +15 featured-claim + 8 SectionChart + 4 ReportRenderer wiring)

- [x] Phase 3.3.C — PeerScatter (PR #43)
    - [x] `peer-grouping.ts` helpers — `groupPeers` parses `<TICKER>: <metric>` descriptions; `extractMedian` pulls `Peer median: …` claims; `extractSubject` cross-joins Valuation + Quality for the report's own ticker
    - [x] Recharts `ScatterChart` PeerScatter component — peers / subject / median as three Scatter series; subject 9px slate-900, peers 6px slate-500, median slate-400 cross; reuses `formatClaimValue` for axes
    - [x] Vite auto-chunking hoists recharts into a shared chunk used by both SectionChart and PeerScatter; main bundle 76.92 KB gz (was 76.25; +0.7 KB); per-component chunks 4.84 KB + 6.03 KB; recharts chunk 100 KB shared
    - [x] 94/94 frontend tests pass (was 67; +17 peer-grouping + 7 PeerScatter + 3 ReportRenderer wiring)
    - [x] EARNINGS focus mode falls back to peers + median only (no Quality section to extract subject's gross margin from)

- [x] Phase 3.4 — Eval rubric history *(this branch)*
    - [x] `_claim_numeric_values` widens to yield each history point alongside the snapshot
    - [x] Module + function docstrings updated to document the history-aware mode
    - [x] 6 new rubric unit tests: prose-cites-history, "rose from X to Y", percent display of historical fraction, anti-regression on fabrication, pre-3.2 backwards compat, cross-section history matching
    - [x] 25/25 rubric tests pass (was 19; +6); ruff clean
    - [x] Live-LLM golden eval auto-benefits via existing AAPL/full case

## Blocked / waiting

-
