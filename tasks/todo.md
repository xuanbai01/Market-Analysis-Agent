# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [ADR 0003](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: free data only, citation discipline non-negotiable. Phase 1 infrastructure complete.
>
> **Product shape:** [ADR 0004](../docs/adr/0004-visual-first-product-shape.md) — visual-first, delta-driven. Multi-year history rendered as charts; LLM commentary stays short. **Not** chasing Morningstar-depth analyst narrative.
>
> **Surface shape:** [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md) — pivot from "click Generate → static report" to **symbol-centric dashboard** (`/symbol/:ticker`) with adaptive layouts. Same backend; new frontend architecture.

## In progress

- **Phase 4 — Symbol-centric dashboard rebuild** (Strata design from user's prototyping session). **4.0 → 4.5.C done (PRs #46–#59 — #59 ready for review); 4.6 Compare page is next.** See [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md).

## Handoff — pickup notes (2026-05-04)

If you're picking this up after a gap, here's the orientation in three lines:

1. **Read [CLAUDE.md](../CLAUDE.md) "Current state" first** — it tracks what's done through 4.5.C with bundle sizes, test counts, and inline summaries of every shipped PR.
2. **Next concrete work is Phase 4.6 — Compare page.** Spec is below. Bundle headroom is 1.58 KB so the new `/compare` route needs `React.lazy()` chunk-splitting from day one.
3. **Open PR is #59 (Phase 4.5.C — Layout polish).** If it's still open, merge it before starting 4.6 — the docs in `tasks/todo.md` and `CLAUDE.md` already reflect 4.5.C as done. If it's already merged, the worktree is clean and you can branch off `main`.

**Three known followups not blocking 4.6:**

- **Vite HMR cache misses file mtime in `.claude/worktrees/...`** — see [tasks/lessons.md](lessons.md). Workaround: trust unit tests + `vite build` for verification when the dev preview shows stale content. Fix candidate: add `server.watch.usePolling: true` to `vite.config.ts`. Low priority.
- **Pre-existing ValuationCard ESLint warning** (`Unnecessary escape character: \-` at `frontend/src/components/ValuationCard.tsx:36`). Benign; tracking unfix because the regex pattern reads more clearly with the explicit escape. Drop the backslash if you ever want a clean lint pass.
- **Real-LLM dogfood for 4.5.B's prompt change** — the synth prompt now receives `layout_signals` as framing context for distressed names. Unit-tested, but the actual narrative-tone shift on a real RIVN report hasn't been verified end-to-end. Naturally lands when 4.8 dogfood gate runs.

**`tasks/lessons.md`** captured four lessons during 4.4 → 4.5 — read before non-trivial work to avoid retreading them.

## Phase 4 — Symbol-centric dashboard (active)

> **Why this is Phase 4:** dogfooding the Phase 3 visual depth (sparklines, section charts, peer scatter) against MSFT / NVDA / AMZN / AAPL / RIVN locally surfaced that the *data and visualization were right* but the *container was wrong*. "Click Generate → scroll a static report" feels like a generated artifact, not a tool. profitviz / stockanalysis / finchat all converge on a symbol-centric dashboard for a reason. See [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md) for the full reasoning.
>
> **What this is NOT:** a polish task. The Strata design pivot is structural — adaptive layouts (RIVN reframes to cash runway / burn / risk; healthy names show valuation + quality + growth), bookmarkable URLs, sidebar persistence, and Compare mode are all impossible in the report shape regardless of how much polish we apply.
>
> **Phase 3 status:** schema (3.1) ✅; data-tool history (3.2.A–F) ✅; frontend visualization (3.3.A–C) ✅; eval rubric history (3.4) ✅. All survives. The frontend visualizations get partially deprecated — `Sparkline` and the chart helpers live on; `SectionChart` / `PeerScatter` / `ReportRenderer` get replaced by Strata variants. The `/v1/research/{symbol}` endpoint and same-day cache layer stay; the renderer that consumes them is what changes.
>
> **Vercel deploy:** moved from Phase 3.5 to Phase 4.8. Holding the deploy until the new UI lands rather than shipping a public deploy that immediately needs a redesign.

### 4.0 Token system + sidebar shell + route refactor ✅ done *(this PR)*

- [x] **Tailwind extend with Strata tokens** — slate base (canvas / surface / raise / line / border / muted / dim / fg / hi), 9 semantic accents (valuation / quality / growth / cashflow / balance / earnings / peers / macro / risk), 4 state colors (pos / neg / neutral / highlight), Inter + JetBrains Mono font families, `letterSpacing.kicker` for category labels.
- [x] **`SidebarShell`** — 72 px fixed-width left rail with brand mark + 5 nav buttons. Search wired (opens stub modal); Compare / Watchlist / Recent / Export disabled in 4.0 (activate in 4.6/4.7).
- [x] **`RequireAuth`** — route guard; redirects to /login when no token; preserves original URL via location state.
- [x] **`AppShell`** — sidebar + main outlet; persistent across authenticated routes.
- [x] **`LandingPage`** — `/` route. Centered search bar + Recent reports list (`PastReportsList` integration). Submit navigates to `/symbol/:ticker` (uppercased).
- [x] **`SymbolDetailPage`** — `/symbol/:ticker` route. Reads URL param, fetches via existing TanStack Query path, renders hero placeholder + restyled `ReportRenderer`. Centralized 401 → clear token + bounce to /login.
- [x] **`react-router-dom@^6`** added (~7 KB gz net after the rest of the changes).
- [x] **Existing components restyled for dark theme** — `ReportRenderer`, `Sparkline`, `ConfidenceBadge`, `LoadingState`, `ErrorBanner`, `PastReportsList`, `LoginScreen` all switched to Strata tokens.
- [x] **Deleted** — `Dashboard.tsx`, `ReportForm.tsx` (replaced by AppShell + LandingPage + SymbolDetailPage split).
- [x] **111/111 frontend tests pass** (was 94; +17). Bundle 83.84 KB gz (was 76.92; +7 KB) — under 100 KB budget.
- [ ] **`SearchModal` (deferred to 4.7)** — Search button currently focuses the landing-page input; modal lands when watchlist + recent functionality also do.
- [ ] **Backend additions deferred to 4.1** — `/v1/market/:ticker/prices?range=60D` and logo URL resolution land alongside hero card implementation.

### 4.1 Hero card + Earnings card ✅ done *(this PR)*

- [x] **`HeroCard`** — three-column glow-shadowed card. Logo letter circle + ticker eyebrow + sector tag + name + big tabular price + colored delta + MCAP/VOL/52W meta (left); 60-day price chart with 6 range pills (center); 3 featured stats with peer/historical sub-context (right).
- [x] **`EarningsCard`** — replaces ReportRenderer's Earnings claims table. "X of N beat consensus" headline + Next print date + EpsBars chart + 3 stat tiles (Beat rate / Surprise μ / EPS TTM, the last computed client-side from history).
- [x] **`LineChart` primitive** — hand-rolled SVG, default 560×140, configurable stroke + optional area fill. Used by HeroCard's price chart.
- [x] **`EpsBars` primitive** — 20-bar SVG chart. Beat/miss coloring (strata-pos / strata-neg); estimate ticks render as horizontal lines for periods with matching estimates; negative actuals (RIVN-class) render with a zero baseline.
- [x] **`hero-extract.ts`** — pure helper pulls hero data via description matching; reads top-level `name`/`sector` from ResearchReport.
- [x] **Backend: `GET /v1/market/:ticker/prices?range={60D|1Y|5Y}`** — read-through `candles` cache; falls through to `ingest_market_data` (yfinance) on cache miss with 80% coverage threshold.
- [x] **Backend: 4 new fundamentals claims** — `name`, `sector_tag`, `fifty_two_week_high`, `fifty_two_week_low`. Plus orchestrator lifts `name`/`sector` to top-level `ResearchReport.name`/`.sector` (Pydantic + Zod schema mirrored).
- [x] **Visible after 4.1:** `/symbol/AAPL` renders a real hero region with price chart + 3 KPIs + 20-quarter earnings history. Backend 522/522, frontend 146/146 tests pass; main bundle 86.82 KB gz.

### 4.2 Quality scorecard + Valuation matrix + PeerScatter v2 ✅ done *(this PR)*

> **Scope:** all-frontend. No backend changes. Replaces ReportRenderer's
> Valuation / Quality / Peers cards with dedicated Strata variants;
> introduces two hand-rolled SVG primitives so the 4.2 work doesn't lean
> on Recharts. The Recharts shared chunk stays for now (SectionChart still
> uses it for Capital Allocation / Macro until 4.3); PeerScatter's recharts
> dep is gone — the file is deleted.

- [x] **`MetricRing` primitive** — circular SVG ring with center value, label below, optional sub-label. Configurable accent + ratio (0–1, clamped). Hand-rolled. `data-testid='metric-ring'`. 8 tests.
- [x] **`MultiLine` primitive** — 2-4 series on a shared axis with x-labels + 3 horizontal grid lines + per-series legend chip row. Hand-rolled SVG. Used by QualityCard's gross/operating/FCF margin chart. `data-testid='multi-line'`. 8 tests.
- [x] **`QualityCard`** — replaces ReportRenderer's Quality section card. Header (kicker + ticker eyebrow) → 3 MetricRings (ROE, ROIC TTM, FCF margin) → MultiLine (Gross / Operating / FCF margins) → hybrid claims table: default 6 (ROE / Gross margin / Operating margin / FCF margin / ROIC / Net profit margin) with "Show all 16" disclosure. Disclosure auto-hides when there are ≤6 claims to avoid the "show all 5" awkward case. 8 tests.
- [x] **`ValuationCard`** — replaces ReportRenderer's Valuation + Peers section cards. Header → 4-cell grid (P/E trailing, P/E forward, P/S, EV/EBITDA), each cell shows subject value + peer median + horizontal percentile bar (peer min → max with subject dot + median tick) → PeerScatterV2 below. 7 tests.
- [x] **`PeerScatterV2`** — hand-rolled SVG (replaces 3.3.C Recharts version). 3 axis presets via inline pill row: **P/E × Gross Margin** (default), **P/S × Gross Margin**, **EV/EBITDA × Gross Margin**. All three pairs drawn from the 4 existing `PEER_METRICS` so 4.2 needs no backend change. Subject as larger labeled colored dot; peers as smaller dots with inline ticker labels; median as a small cross. X + Y axis labels + min/max ticks visible. 9 tests.
- [x] **`quality-extract.ts`** — `extractQualityRings(section)` returns `{roe, roic, fcfMargin}`; `extractMarginSeries(section)` returns 3 history series for MultiLine; `extractPrimaryQualityClaims(section)` + `extractAllQualityClaims(section)` for the 6+expand split. 11 tests.
- [x] **`valuation-extract.ts`** — for each of the 4 metrics: `{subject, peerMedian, peerMin, peerMax, percentile}`. Reads Valuation section for subject and Peers section for peer/median values. Percentile = `count(peer ≤ subject) / peer_count`; null when subject missing or peer set < 2. 8 tests.
- [x] **`peer-grouping.ts` extension** — generic `groupPeersForAxes(claims, xMetric, yMetric)` and `extractMedianForAxes(claims, xMetric, yMetric)` so PeerScatterV2 can pivot axes; legacy `groupPeers` / `extractMedian` re-implement on top of the generic helpers. 9 new tests.
- [x] **SymbolDetailPage** — plucks Quality section; renders `<ValuationCard report={…}/>` and `<QualityCard section={…}/>` above ReportRenderer; ReportRenderer's `excludeSections` widens to `["Earnings","Valuation","Quality","Peers"]`.
- [x] **Deleted** `components/PeerScatter.tsx` + `.test.tsx` (3.3.C Recharts version replaced by v2). ReportRenderer's lazy `PeerScatter` import + isPeers handling removed; SectionChart still lazy-loaded for Capital Allocation / Macro.
- [x] **Net result:** 204/204 frontend tests pass (was 146 + 7 PeerScatter; +65 net new across 5 components + 2 extractors + 1 lib extension). Backend untouched at 522/522. Main bundle 90.20 KB gz (was 86.82; +3.4 KB; under 100 KB budget). SectionChart chunk now solo at 103 KB gz (used to share with PeerScatter; loads only on-demand for sections with featuredClaim). Typecheck + lint clean.

**Design decision: axis-preset list.** The original sketch was *P/E × Gross Margin / P/S × Operating Margin / EV/EBITDA × ROIC*. Backend `fetch_peers` only carries 4 metrics (`trailing_pe`, `p_s`, `ev_ebitda`, `gross_margin`); adding operating_margin + ROIC to peers requires per-peer TTM compute (the ROIC formula already exists for the subject in `fundamentals_history.py`). Deferring that backend extension keeps 4.2 frontend-only / one PR. The presets above are all peer-coverage-complete. Richer axis options come back in 4.5/4.8 if dogfooding asks for them.

### 4.3.A Per-share growth + Cash & capital + Risk diff + Macro ✅ done *(this PR)*

> **Scope:** all-frontend. No backend changes. Fills the row-3 (Per-share
> growth) and row-4 (Cash & capital + Risk diff + Macro) cards from the
> Strata design's `direction-strata.jsx`. Capital Allocation remains in
> ReportRenderer for now (its 6 non-history claims — dividend_yield,
> buyback_yield, sbc_pct_revenue, short_ratio, shares_short, market_cap
> — don't fit the 4 new cards cleanly; revisit in 4.4 if the context
> band absorbs them).

- [x] **`PerShareGrowthCard`** — 5 per-share history series (Revenue, Gross Profit, Op Income, FCF, OCF), each **rebased so the series' first point = 100**, plotted via existing `MultiLine` primitive. Below the chart: 5 multiplier pills ("Rev 6.2×", "GP 7.2×", etc.). Reads from Quality section. 7 tests.
- [x] **`CashAndCapitalCard`** — cross-section card. Top stack: `MultiLine` of CapEx + SBC per-share (from Capital Allocation). Bottom stack: `MultiLine` of Cash + Debt per-share (from Quality). Highlight box: Net cash / share = (cash − debt) at latest snapshot, colored pos/neg. 7 tests.
- [x] **`RiskDiffCard`** — inline horizontal bar chart of `{added, removed, kept, char_delta}` from the Risk Factors section's existing 4 claims. Prose summary below ("Disclosure expanded. Net +9 ¶ ..." / "Disclosure shrank ..." / "Disclosure stable ..."). When 4.3.B lands the Haiku categorizer, the bars become per-category — the card already gates on extractor returning null so pre-4.3.B reports keep rendering. 6 tests.
- [x] **`MacroPanel`** — vertical stack of mini area-chart panels (one per FRED series). Each panel: kicker label + current value badge + 36-month sparkline area chart via existing `LineChart` primitive (`areaFill={true}`). Reads from Macro section. 5 tests.
- [x] **`growth-extract.ts`** — `extractGrowthSeries(section)` returns 5 `MultiLineSeries` (rebased to first-point = 100); `extractGrowthMultipliers(section)` returns 5 `latest / first` ratios. Drops series whose history is empty or whose first value is zero. 8 tests.
- [x] **`cash-capital-extract.ts`** — `extractCapexSbcSeries(capAlloc)` + `extractCashDebtSeries(quality)` + `extractNetCashPerShare(quality)`. Net cash supports negative (debt-heavy) values. 10 tests.
- [x] **`risk-extract.ts`** — `extractRiskDiffBars(section)` returns `{added, removed, kept, charDelta} | null`; `extractRiskDiffSummary(section)` returns the prose framing (`"expanded"` / `"shrank"` / `"stable"`) + signed `netDelta`. 9 tests.
- [x] **`macro-extract.ts`** — `extractMacroPanels(section)` returns `{id, label, latest, history, observationDate}[]`. Reads `<label> (latest observation)` (value-bearing, history-bearing), `<label> observation date`, and the metadata claim `Human-readable label for FRED series <id>` for the optional id. Skips series with non-numeric latest or empty history. 6 tests.
- [x] **SymbolDetailPage** — plucks Quality, Capital Allocation, Risk Factors, Macro sections; renders `<PerShareGrowthCard>` after QualityCard, then a 3-column grid `<CashAndCapitalCard> | <RiskDiffCard> | <MacroPanel>` matching the design's row-4 layout. Widens `excludeSections` to `["Earnings","Valuation","Quality","Peers","Risk Factors","Macro"]` — Capital Allocation stays through ReportRenderer.
- [x] **Net result:** 262/262 frontend tests pass (was 204; +58 net new across 4 cards + 4 extractors). Backend untouched at 522/522. Main bundle 92.93 KB gz (was 90.20; +2.7 KB; under 100 KB budget). SectionChart chunk unchanged at 103 KB gz (still loads on-demand for Capital Allocation's featured-claim chart). Typecheck + lint clean.

### 4.3.X Data correctness + format-helper unit hint *(this PR)*

> **Why this PR exists:** dogfooding the post-PR-#50 dashboard surfaced
> six substantive bugs in five minutes — see [tasks/dogfood-2026-05-03.md](dogfood-2026-05-03.md).
> The cards look great but the *numbers are wrong* in places that matter
> (ROE displayed as `1.41` instead of `141%`, dividend yield as `39.09%`
> instead of `0.39%`, per-share dollars as `16.02%` instead of `$0.16`).
> Plus a critical FK violation in the prices route that breaks the
> HeroCard chart for every ticker that isn't NVDA or SPY.
>
> **Why before 4.4 / 4.5:** both downstream phases compound on the data
> + format layer. 4.5's adaptive-layout signals derive from the same
> `Claim.value`s being misformatted today. 4.4's per-card narratives
> need a clean per-card narrative-strip surface (item 3 below blocks).
> Cheaper to fix the foundation now than to layer features on a moving
> foundation.

- [x] **Schema unit hint** — `Claim.unit: ClaimUnit | None = None` shipped (Pydantic + Zod). 33 keys in `app/services/fundamentals.py` annotated via parallel `_UNITS` dict + import-time `assert _UNITS == CLAIM_KEYS` so a forgotten annotation fails loudly. Frontend `formatClaimValue(value, unit?)` dispatches deterministically; falls through to legacy heuristic when unit is undefined/null. Wired into QualityCard rings + claim table, ReportRenderer claim table, HeroCard ROIC/FCF, CashAndCapitalCard net cash. Fixes Bugs 2/3/4. *(Other tools — `peers`, `earnings`, `macro`, `research_tool_registry`, `form_4`, `holdings_13f` — keep their unit field default to `None` for now; the legacy heuristic handles their values correctly because the bugs were concentrated in `fetch_fundamentals`. Cleanup follow-up if/when those tools start rendering values that hit the same edge cases.)*

- [x] **Symbols upsert in price ingest path** — `data_ingestion.py::ingest_market_data` does `pg_insert(Symbol).on_conflict_do_nothing` before the candle insert. Test in `tests/test_market_prices.py::test_prices_succeeds_for_symbol_not_pre_seeded` asserts 200 + `Symbol` row created. Fixes Bug 1.

- [x] **Drop section narrative from `PerShareGrowthCard`** — `section.summary` block removed; comment notes per-card narratives return in 4.4. Test flipped to assert the prose is NOT in the card. Fixes Bug 5.

- [x] **HeroCard top-level metadata backfill** — `backfill_top_level_metadata(report)` helper added to `research_orchestrator.py`; called from `research.py` router after `lookup_recent` returns a hit. Lifts `Company name` / `Resolved sector tag` claim values to top-level when `report.name`/`.sector` are None. 3 unit tests pin happy path + preserve-existing-values + missing-claims-no-error. Fixes Bug 6 (a). VOL + 52W (b) come back automatically once fresh reports regenerate.

- [x] **Loading-state copy + ghost skeleton** — copy widened to "30–90 seconds"; ghost skeleton renders the dashboard's 4 row layout (Hero + 2-col 40/60 + 3-col grid) under `animate-pulse`. Fixes Bug 7.

- [x] **Cosmetic backlog from PR #50 audit** — all four shipped:
  - HeroCard exchange chip combining ticker + sector token (`data-testid='hero-exchange-chip'`).
  - ValuationCard "n = X peers · sector medians" annotation (`data-testid='valuation-peer-count'`); `countPeers` helper extracts distinct tickers from `<TICKER>: <metric>` claim descriptions.
  - QualityCard "MARGINS · 5Y" sub-kicker with inline GM/OM/FCF values via the same `formatClaimValue` (`data-testid='quality-margins-subkicker'`).
  - `MultiLine` paths switch to Catmull-Rom-to-Bezier monotone cubic curves (tension 1/6); endpoints mirror the nearest neighbor so curves start/end tangent without overshoot.

- [ ] **Defer:** Bug 8 (mid-flight nav silently cancels POST) — small standalone ticket; fix is risky enough to keep out of a polish PR.

- [x] **Capture lessons** — entry added to `tasks/lessons.md` covering (a) the heuristic-formatter trap, (b) the test-fixture dogfood gap, and (c) the symbols-FK seeding gotcha for /v1/market/:ticker/prices.

- [x] **Update test counts** — backend 522 → **531** (+9), frontend 262 → **277** (+15). Updated in `CLAUDE.md`, `docs/architecture.md`, this file. Main bundle 92.98 → **93.95 KB gz** (+0.97; under 100 KB budget, ~6 KB headroom retained).

### 4.3.X review *(filled in after the GREEN + docs commits land)*

- **What changed in shape:** `Claim.unit` is the only new schema field; everything else lives behind it (frontend dispatch + tool annotations) or is pure presentation (cosmetic backlog) / single-line correctness (symbols upsert) / single helper (backfill_top_level_metadata).
- **What didn't change:** the surface of `POST /v1/research/{symbol}` is unchanged for callers that don't read `unit` — backwards-compat default `None` keeps pre-4.3.X cached JSONB rows round-tripping.
- **Net deltas:** backend +9 tests, frontend +15 tests, main bundle +0.97 KB gz. No new dependencies, no new chunks.
- **Followups noted but deferred:** unit annotations for the other 5 tools (peers / earnings / macro / research_tool_registry / form_4 / holdings_13f) — wait until a specific bug surfaces; cancel-on-nav (Bug 8) — small standalone ticket; per-card narratives — return in 4.4.

### 4.3.B Risk Haiku categorizer *(this PR)*

> **Why:** RiskDiffCard currently shows 4 aggregate bars (added /
> removed / kept / char-delta) — useful but missing the "what kind of
> risk grew?" signal. The Strata design's screenshot 1 shows 8
> per-category bars (AI / supply / cyber / competition / IP / macro /
> regulatory / other). The aggregates miss the texture: NVDA might
> add 5 paragraphs about export controls and remove 2 about FX while
> a competitor adds 4 about competition and 3 about cybersecurity —
> both look like "+3 ¶" in the aggregate.
>
> Cost discipline: Haiku-only (~$0.001-0.005/report on typical 10–15
> paragraph diffs). Skipped entirely when added+removed = 0 so a
> stable disclosure costs nothing. Backwards-compat: pre-4.3.B
> cached rows lack the per-category fields, the card falls back to
> the aggregate bars.

#### Backend

- [x] **`RiskCategory` enum** in `app/schemas/ten_k.py` — 9 categories shipped: `AI_REGULATORY`, `EXPORT_CONTROLS`, `SUPPLY_CONCENTRATION`, `CUSTOMER_CONCENTRATION`, `COMPETITION`, `CYBERSECURITY`, `IP`, `MACRO`, `OTHER`. String-valued so JSONB serializes as plain strings.

- [x] **Extend `Risk10KDiff`** with `category_deltas: dict[RiskCategory, int] = Field(default_factory=dict)` — net delta per category. Default empty so pre-4.3.B JSONB rows round-trip unchanged.

- [x] **`app/services/risk_categorizer.py`** — `categorize_risk_paragraphs(added, removed)` short-circuits on empty inputs, otherwise issues one `triage_call` (Haiku 4.5) with the forced `RiskCategorization` tool schema. Drops zero-net buckets and defends against out-of-range indices in the model's response.

- [x] **Wire categorizer into `extract_10k_risks_diff`** — `try/except` around the call so categorizer failures (rate limit / network) degrade to `category_deltas={}` rather than failing the whole diff. Adds `category_buckets` count to the existing `log_external_call` output summary.

- [x] **`_build_risk_factors` in `research_tool_registry.py`** — emits one extra `Claim` per non-zero category with description `"<Label> risk paragraph delta vs prior 10-K"`. `_RISK_CATEGORY_LABELS` map centralizes the labels — frontend's `risk-extract.ts` mirrors them verbatim, kept in sync via `risk-extract.test.ts` description-match assertions.

- [x] **Frontend `risk-extract.ts`** — `extractRiskCategoryDeltas(section)` returns null when no per-category claims are present, otherwise a sorted `RiskCategoryDelta[]` (largest |delta| first). New `RiskCategory` type union + `RISK_CATEGORY_LABELS` map mirroring backend.

- [x] **`RiskDiffCard.tsx`** — when `extractRiskCategoryDeltas` returns non-null, renders the new `CategoryBars` SVG (positive deltas in risk accent, negative in quality accent, scaled to absolute max). Otherwise falls back to the existing 4-bar aggregate.

- [x] **Tests** — backend 531 → 544 (+13: 4 schema + 5 categorizer + 2 ten_k integration + 2 registry); frontend 277 → 285 (+8: 5 extractor + 3 card).

- [x] **Cost / observability** — categorizer skips Haiku entirely on `len(added)+len(removed)==0`. `log_external_call` records `category_buckets` count so cost-per-report is chartable from the A09 stream. Real-LLM cost validation deferred to dogfooding (target: ≤$0.005/report, $0 stable).

- [x] **Bundle** — main 93.95 → 94.40 KB gz (+0.45). Under 100 KB budget; ~5.6 KB headroom retained for 4.4. SectionChart on-demand chunk unchanged at 103.01 KB gz.

- [x] **Update test counts** — backend 531 → **544**, frontend 277 → **285**. Updated in `CLAUDE.md`, `docs/architecture.md`, this file.

### 4.3.B review *(filled in after the GREEN + docs commits land)*

- **What changed in shape:** one new enum (`RiskCategory`) and one new dict field on `Risk10KDiff`; one new service module; one new wire-through; one new frontend extractor + bar chart. No new top-level routes, no schema breaks, no new dependencies.
- **What didn't change:** the 4 aggregate `Claim`s still ship for every diff so the existing card render path + extractor work on pre-4.3.B JSONB rows + on stable disclosures (the categorizer skips the Haiku call and `category_deltas` lands as `{}`).
- **Net deltas:** backend +13 tests / +1 service module; frontend +8 tests / +1 helper / 1 component upgrade; main bundle +0.45 KB gz. No ADR needed.
- **Followups noted:**
  - Real-LLM cost telemetry from a few dogfooded reports → confirm/refute the $0.005-target estimate.
  - The 9-bucket catalog will need to grow if `OTHER` dominates real diffs. Add a guardrail in 4.4 dogfooding to flag issuers where `OTHER >= 50%` of their bucketed paragraphs.

### 4.3.B.1 Layout polish + range pills + responsive SVGs *(this PR)*

> **Why:** dogfooding PR #51 surfaced four UX rough edges that don't
> warrant a phase rename but visibly hurt the dashboard's trust:
> price-chart pills 1D / 5D / 1M all rendered the same 60-bar chart
> (no client-side slicing); EarningsCard + PerShareGrowthCard had
> hundreds of pixels of empty canvas below their content (no row
> partner of similar height); chart elements escaped card borders on
> narrow viewports because every primitive hardcoded its width.

- [x] **Price chart pills** — `frontend/src/lib/price-range.ts::sliceForRange` slices the 60D feed to last 2 / 5 / 22 points for 1D / 5D / 1M; passes through unchanged for 3M / 1Y / 5Y. HeroCard wires it in front of LineChart's data prop and the subtitle reflects the actual span shown ("22 trading days" not "60 trading days").

- [x] **EarningsCard `RecentPrints`** — last-4-quarters mini-table below the 3 stat tiles. Period · actual · estimate · surprise %, surprise color-coded pos/neg. Hidden when section has no EPS history. Adds substantive content (not just height-padding) — recent prints is canonical for an earnings card.

- [x] **PerShareGrowthCard CAGR annotations** — each multiplier pill grows a sub-line "+58.3% / Q" computed via `extractGrowthCagr` (multiplier^(1/n_periods) − 1, defends against sign-change endpoints + zero/negative ratios). Em-dash on null. ~30px per pill row, closes most of the blank-canvas gap to ValuationCard.

- [x] **Responsive SVG widths** — LineChart, EpsBars, MultiLine, RiskDiffCard's aggregate bars switched from hardcoded `width` props to `width="100%"` with viewBox preserving internal coords. Chart elements stay inside the card border at any viewport. Height stays numeric so visual height is stable. Same pattern Sparkline already used.

- [x] **LineChart path discriminators** — `data-line-stroke` / `data-line-area` on the two paths so tests can count segments on the line specifically (the area path adds 3 extra commands when `areaFill={true}`).

- [x] **Tests** — frontend 277 → **295** (+18: 7 price-range/Hero, 3 RecentPrints, 3 CAGR, 4 SVG-width updates, 1 EarningsCard label-collision fix). Backend untouched at 531/531.

- [x] **Bundle** — main 93.95 → **94.46 KB gz** (+0.51). Under 100 KB budget; ~5.5 KB headroom retained for 4.4. SectionChart on-demand chunk unchanged at 103.01 KB.

### 4.3.B.2 Price chart axes + hover tooltip *(this PR)*

> **Why:** dogfooding PR #51 + #53 surfaced that the hero price chart
> read as decorative — the line shape was visible but you couldn't
> read prices, dates, or hover over it for exact values. The 4.1
> docstring (``no axes, no tooltip, no grid — the hero card composes
> those separately around the chart``) was a deferral that the hero
> never came back to.

- [x] **`LineChart` axis labels** — new opt-in `showAxes` prop renders y-axis min/max price labels formatted as `$X.XX` on the left edge and x-axis first/last date labels (UTC-formatted to avoid TZ drift, since yfinance timestamps bars at UTC midnight). Off by default so any non-Hero caller stays lean. New testids `line-chart-y-axis-{min,max}` + `line-chart-x-axis-{start,end}` for regression assertions.

- [x] **`LineChart` hover tooltip** — new opt-in `showTooltip` prop wires `onMouseMove` and `onMouseLeave` on the SVG. Cursor x maps to viewBox space via the SVG's bounding rect (with a happy-dom fallback for tests); nearest data point selected by linear scan. Three new SVG artifacts under stable testids: `line-chart-hover-{guide,dot,tooltip}` — guide is a vertical dashed line; dot is a filled circle on the line at the nearest point; tooltip is a small floating panel with date + price. Tooltip flips left when too close to the right edge so it stays in-frame.

- [x] **HeroCard wiring** — sets `showAxes={true} showTooltip={true}` on its LineChart. Other consumers (none today) keep the lean default.

- [x] **Bonus: rescue per-category bars regression** — the PR #52 ↔ PR #53 merge silently dropped the conditional render of `CategoryBars` in `RiskDiffCard.tsx`; the `CategoryBars` function survived in the file but was never called from JSX. Two of PR #52's tests were failing on main because of it. Restored the `{categoryDeltas ? <CategoryBars/> : <svg .../>}` ternary. Also made `CategoryBars`' SVG responsive width (matching what PR #53 did for the aggregate bars).

- [x] **Tests** — frontend 295 → **314** (+19: 13 LineChart axes/hover, 3 HeroCard wire-through, 2 rescued RiskDiffCard tests, 1 prior-test fix). Backend untouched at 544/544.

- [x] **Bundle** — main 94.46 → **95.71 KB gz** (+1.25). ~4.3 KB headroom retained under the 100 KB budget. SectionChart on-demand chunk unchanged at 103.01 KB.

### 4.4 News + Business + section narratives

> **Split:** ship as two PRs to keep each reviewable.
> - **4.4.A — ContextBand (Business + News)** *(this PR)*. The "above the grid" content the user expects from a research dashboard.
> - **4.4.B — Per-card section narratives** *(follow-up)*. Cross-cutting concern (touches every card + the synth call schema).

#### 4.4.A ContextBand: Business + News *(this PR)*

> **Why:** the dashboard at `/symbol/:ticker` opens straight into Hero → numeric grid. There's no "what does this company *do*" card and no "what's the latest news" feed. Both are canonical for a research dashboard and Strata's screenshot 5 calls them out as the ContextBand layer between Hero and the row-2 grid.

**Backend:**

- [ ] **`app/services/business_info.py`** — new tool `async def fetch_business_info(symbol)` returning `dict[str, Claim]`. Pulls from yfinance `Ticker.info`: `longBusinessSummary` (~3-5 sentences), city/state/country (joined as HQ string), `fullTimeEmployees`. Founded year skipped — yfinance doesn't carry it cleanly. One `log_external_call` record under service id `yfinance.business_info`.
- [ ] **`app/services/news.py`** — new `async def fetch_news(symbol) -> dict[str, Claim]`. Opens its own AsyncSession, calls `news_repository.list_news(symbol, hours=168, limit=30)`, calls `news_categorizer.categorize_news_headlines` to classify each headline, returns one Claim per article with description=title, value=sentiment, source.url=article_url, source.detail=`"category=<bucket>"`. Returns `{}` cleanly when no articles exist (no upstream-provider call yet — ingestion stays driven by `POST /v1/news/ingest`; revisit if dogfooding shows stale data).
- [ ] **`app/services/news_categorizer.py`** — mirrors `risk_categorizer.py`. Single Haiku call with a forced-tool `NewsCategorization` schema (`list[HeadlineClassification(index, category, sentiment)]`). Two enums: `NewsCategory` (EARNINGS / PRODUCT / REGULATORY / M_AND_A / SUPPLY / STRATEGY / OTHER, 7 buckets) + `NewsSentiment` (POSITIVE / NEUTRAL / NEGATIVE). Short-circuits on empty input. Defensive on out-of-range indices. Cost target ≤$0.005/report on a typical 20-30 headline batch.
- [ ] **`research_tool_registry.py`** — add `Business` and `News` sections to `SECTIONS_BY_FOCUS[Focus.FULL]` (placed first so the orchestrator processes them before the numeric sections). New `_build_business` + `_build_news` builders that pass through the tool's `dict[str, Claim]` directly. EARNINGS focus: News only (Business is full-research-only).
- [ ] **`research_orchestrator.py`** — wire `fetch_business_info` + `fetch_news` into `TOOL_DISPATCH`. Cache miss → fan-out runs them alongside fundamentals/peers/etc. via `asyncio.gather(return_exceptions=True)`.

**Frontend:**

- [ ] **`lib/business-extract.ts`** — `extractBusinessInfo(section)` returns `{summary: string|null, hq: string|null, employeeCount: number|null}` from a Business section's claims.
- [ ] **`lib/news-extract.ts`** — `extractNewsItems(section)` returns `NewsItem[]` parsed from each Claim (description = title; value = sentiment; source.url = article url; source.detail's `category=<bucket>` substring → category enum). Drops malformed items.
- [ ] **`components/BusinessCard.tsx`** — single card. Header eyebrow "BUSINESS · {ticker}" + 1-paragraph summary (truncate to ~3 lines with overflow `...`) + small metadata row (HQ · {N} employees). Renders nothing when summary is empty.
- [ ] **`components/NewsList.tsx`** — header eyebrow "NEWS · LAST 7 DAYS · {N} items" + filter pill row (ALL / EARNINGS / PRODUCT / REGULATORY / M&A / SUPPLY / STRATEGY / OTHER) + 5 latest items by default with title/source/date + category chip + sentiment dot. "View {N} more" disclosure expands. State: filter selection + expand toggle.
- [ ] **`components/ContextBand.tsx`** — thin 2-col grid wrapper (40/60 same rhythm as rows 2 + 3) holding `<BusinessCard>` (left) + `<NewsList>` (right). Stacks 1-col below `lg:`. Returns null when both children empty.
- [ ] **`components/SymbolDetailPage.tsx`** — pluck `Business` + `News` sections, render `<ContextBand>` between `<HeroCard>` and the row-2 grid.

**Tests:**

- [ ] Backend ~14 new: 5 categorizer (mirrors risk_categorizer's pattern), 3 business_info, 3 news fetch, 2 registry section-builders, 1 orchestrator wire-through.
- [ ] Frontend ~10 new: 2 business-extract, 3 news-extract, 2 BusinessCard, 2 NewsList, 1 ContextBand.

**Bundle math:** main currently 95.71 KB / 100 KB gz → 4.3 KB headroom. NewsList (~3 KB) + BusinessCard (~1 KB) + ContextBand (~0.5 KB) ≈ 4.5 KB total. **Tight — may need to lazy-load NewsList** if final size pushes over budget. Decide after the implementation lands.

#### 4.4.B Per-card section narratives *(this PR)*

> **Why:** the dashboard's dedicated cards (Quality, Earnings,
> PerShareGrowth, RiskDiff, Macro) shipped without inline prose on the
> card itself — only the section's broad ``summary`` was rendered, and
> only in the QualityCard's header. The Strata Rivian screenshot
> (`docs/screenshots/image-1777831007647.png`) calls out a punchy
> 1-2 sentence headline strip at the *bottom* of every card body
> ("Loss is narrowing. EPS −3.82 → −0.78 over 20Q") that's distinct
> from the longer summary in tone and length. PerShareGrowthCard's
> narrative slot (removed in 4.3.X because it duplicated Quality's
> ``summary``) returns cleanly via this card-specific field.

- [x] **Schema: `Section.card_narrative: str | None = None`** in `app/schemas/research.py`. Default ``None`` for back-compat with pre-4.4.B JSONB rows; same 4000-char cap as ``summary``. Mirrored in Zod (`SectionSchema.card_narrative: z.string().nullable().optional()` — optional so existing test fixtures don't churn; the rendering layer handles undefined / null / empty uniformly).
- [x] **Synth tool schema: `SectionSummary.card_narrative: str = ""`** — defaults to empty string; the orchestrator normalizes empty / whitespace to ``None`` when stitching onto `Section.card_narrative` so the frontend's truthy-check uniformly hides the strip.
- [x] **Orchestrator wiring** — new `_resolve_card_narrative(title, summaries)` matches the synth output by title (last-wins on duplicates) and collapses empty / whitespace to `None`. Stitched into the `Section(...)` build alongside `summary` and `confidence`.
- [x] **System prompt extended** — added a 7th rule (`Don't duplicate. summary and card_narrative are different surfaces`), 5 style examples covering each card type, and split rule 5 into two length disciplines (`summary 2-4`, `card_narrative 1-2`). Explicitly instructs the model to write distinct prose for each surface.
- [x] **Eval rubric: `score_factuality` polices `card_narrative` too** — iterates `summary` + `card_narrative` per section so the LLM can't dodge the rubric by writing the hallucination into the card-strip. Pre-4.4.B reports (no `card_narrative`) score the same as before.
- [x] **`NarrativeStrip` primitive** — single component, ~25 lines. Rounded inset card-within-card at the bottom of each card body; `data-testid='card-narrative'`. Returns `null` for null / undefined / empty / whitespace so older cached rows render cleanly.
- [x] **Wired into 5 cards** — QualityCard, EarningsCard, PerShareGrowthCard, RiskDiffCard, MacroPanel each render `<NarrativeStrip text={section.card_narrative} />` at the bottom of their body. PerShareGrowthCard's 4.3.X removal comment replaced with the new slot.
- [x] **SymbolDetailPage** — passes PerShareGrowthCard a Quality section with `card_narrative` cleared so the LLM's single Quality narrative doesn't render twice on the page (QualityCard is the canonical home; 4.5+ will give PerShareGrowth its own section so the prose can differentiate).
- [x] **Cards skipped intentionally** — BusinessCard (its body IS prose), NewsList (filter pills + headlines are the message), ValuationCard / CashAndCapitalCard (cross-section / cross-report sources, ambiguous which section's narrative drives the card). Add later if dogfooding asks for them.
- [x] **Tests** — backend 565 → **577** (+12: 5 schema + 4 orchestrator + 3 rubric); frontend 336 → **353** (+17: 3 schema + 4 NarrativeStrip + 10 per-card pairs).
- [x] **Bundle** — main 97.06 → **97.17 KB gz** (+0.11). ~2.83 KB headroom retained under the 100 KB budget.
- [x] **Verified back-compat** — preview against the cached pre-4.4.B NVDA report confirms all 5 cards render without the strip when `card_narrative` is absent. No console errors.
- [x] **Update test counts** — backend 565 → **577**, frontend 336 → **353**. Updated in `CLAUDE.md`, `docs/architecture.md`, this file.

### 4.4.B review *(filled in after the GREEN + docs commits land)*

- **What changed in shape:** one new optional field on `Section` (`card_narrative`) + one new optional field on the synth's `SectionSummary` tool schema. One new frontend primitive (`NarrativeStrip`). One additional iteration in `score_factuality`. No new top-level routes, no new dependencies, no schema breaks.
- **What didn't change:** ``Section.summary`` still ships verbatim — the rubric still polices it, ReportRenderer still falls back to it, every existing card that surfaces `summary` keeps doing so. Pre-4.4.B JSONB rows round-trip with `card_narrative=None` and the strip is hidden.
- **Net deltas:** backend +12 tests / +1 schema field / +1 synth field / +1 resolver helper; frontend +17 tests / +1 primitive / +1 schema field / 5 cards extended; main bundle +0.11 KB gz.
- **Followups noted:**
  - Real-LLM dogfood will reveal whether the prompt's "don't duplicate" rule actually keeps the model from writing the same prose into both surfaces. If it doesn't, tighten the prompt with negative examples; if it still doesn't, downsize ``summary`` to a deterministic claim-recap and let ``card_narrative`` carry all the prose weight.
  - PerShareGrowthCard's narrative is suppressed at the wiring layer because both it and QualityCard read from Quality. When 4.5+ adds a dedicated growth section (or a derived "Trajectory" claim group), PerShareGrowth gets its own narrative independently.
  - ValuationCard / CashAndCapitalCard could grow strips later — both read from a single primary section (Valuation / Capital Allocation) but share peer / Quality data with neighbors. Hold until a specific dogfood signal asks for them.

### 4.5 Adaptive layout for distressed names *(the differentiator)*

> **Split:** ship as two PRs to keep each reviewable.
> - **4.5.A — Backend layout_signals + Header pills + Hero metric swap** *(this PR)*. The "this dashboard reframes for distress" headline visual.
> - **4.5.B — Card adaptations + section reordering + LLM signal feed** *(follow-up)*. The in-card distressed-mode polish + the structural reordering + the LLM prose adaptation.

#### 4.5.A Backend signals + header pills + hero swap *(this PR)*

> **Why this slice:** the most visible "distress" indicator from the
> Strata Rivian screenshot (`docs/screenshots/image-1777831007647.png`)
> is the *header chrome* — UNPROFITABLE / LIQUIDITY WATCH pills + the
> hero's right-column trio swapping from healthy-name metrics
> (Forward P/E + ROIC + FCF margin) to distressed-name metrics
> (P/Sales + Cash Runway + red FCF margin). Both consume
> ``layout_signals`` read-only — no per-card content changes yet, so
> 4.5.A ships the foundation (signals derivation + payload field) +
> the two read-only consumers in one tight PR.

- [x] **`LayoutSignals` schema** — new Pydantic model in `app/schemas/research.py` with five flags (`is_unprofitable_ttm`, `beat_rate_below_30pct`, `cash_runway_quarters: float | None`, `gross_margin_negative`, `debt_rising_cash_falling`). Defaults to healthy values so pre-4.5 cached JSONB rows hydrate cleanly. Mirrored in Zod with per-field defaults; `HEALTHY_LAYOUT_SIGNALS` exported for test fixtures.
- [x] **`ResearchReport.layout_signals`** field with `default_factory=LayoutSignals` for back-compat.
- [x] **`app/services/research_layout_signals.py`** — pure `derive_layout_signals(report)` reads claim values via description matching (mirrors orchestrator + frontend extractors). Cash runway = `max(net_cash, 0) / |FCF TTM burn|`, computed only when FCF TTM < 0; clamps to `0.0` when net cash is already negative AND burning. Slope signals require ≥ 3 history points.
- [x] **Orchestrator wiring** — `compose_research_report` runs the derivation as a final step before returning; `backfill_layout_signals(report)` helper recomputes for cached pre-4.5 rows (only when current is the healthy default — never overwrites populated values).
- [x] **`/v1/research/{symbol}` cache-hit path** — runs both `backfill_top_level_metadata` and `backfill_layout_signals` so the dashboard's adaptive UI works on cache hits without forcing a fresh LLM call.
- [x] **`HeaderPills`** primitive — renders "● UNPROFITABLE · TTM" / "⚠ LIQUIDITY WATCH" / "● BOTTOM DECILE BEAT RATE" / "▲ DEBT RISING · CASH FALLING" pills above the hero. Returns null when every signal is healthy. `is_unprofitable_ttm` and `gross_margin_negative` collapse to one pill (avoids visual noise on Rivian-class names where both fire). `data-testid='header-pill'`.
- [x] **HeaderPills wired** into SymbolDetailPage at the page top-right above the hero.
- [x] **HeroCard right-column trio swap** — when `is_unprofitable_ttm`: Forward P/E → P/Sales (P/E meaningless for negative E), ROIC TTM → Cash Runway (`~Q remaining`, with "raise likely needed" sub-line when < 6Q), FCF margin label kept but value colored red when negative. Healthy reports render the original Forward P/E + ROIC + FCF margin trio unchanged.
- [x] **`hero-extract.ts`** grows `priceToSales` reader for the swap path.
- [x] **Tests** — backend 577 → **605** (+28: 4 schema, 18 derivation across all 5 signals + edge cases + compound Rivian fixture, 4 orchestrator wire-through + backfill, 2 router cache-hit). Frontend 353 → **371** (+18: 5 schema, 9 HeaderPills, 4 HeroCard swap).
- [x] **Bundle** — main 97.17 → **97.92 KB gz** (+0.75). ~2.08 KB headroom retained under the 100 KB budget.
- [x] **Verified back-compat** — preview against the cached pre-4.5 NVDA report renders the default trio with no header pills (signals backfilled to healthy default). No console errors.
- [x] **Update test counts** — backend 577 → **605**, frontend 353 → **371**. Updated in `CLAUDE.md`, `docs/architecture.md`, this file.

### 4.5.A review *(filled in after the GREEN + docs commits land)*

- **What changed in shape:** one new model (`LayoutSignals`) + one new field on `ResearchReport`. One new derivation module + one new backfill helper. One new frontend primitive (HeaderPills) + one HeroCard trio swap. Zero new top-level routes, zero new dependencies, no schema breaks.
- **What didn't change:** healthy reports render unchanged. Pre-4.5 cached JSONB rows round-trip with `LayoutSignals()` default and the cache-hit backfill recomputes from claims so the dashboard's adaptive UI activates without a fresh LLM call.
- **Net deltas:** backend +28 tests / +1 service module / +1 schema model / +1 helper; frontend +18 tests / +1 primitive / +1 schema field / 1 card swap; main bundle +0.75 KB gz.
- **Followups noted (4.5.B-bound):**
  - In-card distressed-mode polish: EarningsCard "bottom decile" annotation, CashAndCapitalCard runway highlight + raise-needed framing, QualityCard ring colors flip to red when ratio < 0.
  - Section reordering when distressed: Cash & Capital moves up (above Per-share growth); Risk diff moves up (above Macro).
  - Synth prompt receives `layout_signals` as context so Sonnet's narratives adapt ("Trajectory positive, level negative" tone for distressed names).
  - Test fixtures across the layout matrix: healthy mature (NVDA), slowing growth (F or GM), unprofitable growth (RIVN), distressed (TBD by current data). Lands in 4.5.B or 4.5.C.

#### 4.5.B Card adaptations + section reordering + LLM signal feed *(this PR)*

> **Why this slice:** 4.5.A laid the foundation (signals + header chrome).
> 4.5.B closes the loop: the dedicated cards each consume a relevant
> signal, the section grid reorders for distressed names, and Sonnet
> receives the signals as framing context so its narratives adapt
> their tone. Together with 4.5.A, this completes Phase 4.5 — the
> adaptive-layout differentiator from ADR 0005.

- [x] **EarningsCard "bottom decile"** annotation when `beat_rate_below_30pct`. New optional `distressed?: { beat_rate_below_30pct?: boolean }` prop; pill renders next to the X-of-N beat headline. Wired in SymbolDetailPage to read from `layout_signals.beat_rate_below_30pct`.
- [x] **CashAndCapitalCard** runway stat tile when `cash_runway_quarters` is non-null. New optional `runwayQuarters?: number | null` prop. Tile shows "~X.XQ" runway value; sub-line "raise likely needed" + red value coloring when < 6Q. Wired in SymbolDetailPage. FCF-positive companies + pre-4.5 cache rows omit the tile.
- [x] **QualityCard rings flip red** when ROE / ROIC TTM / FCF margin values are negative. Each ring picks `text-strata-neg` (loss accent) when its value < 0, else its default (`text-strata-quality` for ROE/ROIC, `text-strata-cashflow` for FCF margin).
- [x] **SymbolDetailPage row reorder** when distressed (`is_unprofitable_ttm OR cash_runway_quarters < 6`). Default = row 3 Valuation+Growth / row 4 Cash+Risk+Macro. Distressed = row 3 Cash+Risk+Macro / row 4 Valuation+Growth. `data-row='dashboard-row-{3,4}'` markers + `data-row-content` attribute let the reorder logic be regression-tested deterministically.
- [x] **`_build_user_prompt` accepts layout_signals** and emits a "Layout signals (framing context)" block listing active flags + values when at least one is non-default. Sonnet's narratives adapt tone (challenge framing for distressed names) without breaking the citation-discipline contract — every cited number must still appear in the section's claim list.
- [x] **Orchestrator wiring** — `compose_research_report` derives layout_signals from a stub (claims-only) report BEFORE the synth call so the prompt receives them; reuses the same signal value when wrapping the final `ResearchReport` to avoid double-derivation.
- [x] **Tests** — backend 605 → **607** (+2: prompt includes signals when distressed, omits block when healthy). Frontend 371 → **387** (+16: 3 EarningsCard, 5 CashAndCapital, 4 QualityCard, 4 SymbolDetailPage).
- [x] **Bundle** — main 97.92 → **98.37 KB gz** (+0.45). ~1.63 KB headroom remaining under the 100 KB budget.
- [x] **Update test counts** — backend 605 → **607**, frontend 371 → **387**. Updated in `CLAUDE.md`, `docs/architecture.md`, this file.

### 4.5.B review *(filled in after the GREEN + docs commits land)*

- **What changed in shape:** three optional props (one each for EarningsCard, CashAndCapitalCard, the EarningsCard-style on QualityCard's accent) + one optional kwarg on `_build_user_prompt`. Plus a SymbolDetailPage IIFE that picks between two row orderings based on a derived `isDistressed` boolean. No new components, no schema changes.
- **What didn't change:** healthy reports render unchanged. Pre-4.5 cached rows (where signals are at the healthy default after the 4.5.A backfill) take the unchanged code path everywhere.
- **Net deltas:** backend +2 tests / +1 prompt helper / 1 prompt-builder signature change; frontend +16 tests / 4 cards extended / 1 IIFE-based reorder; main bundle +0.45 KB gz.
- **Followups noted:**
  - **Live-LLM dogfood with a distressed name** (RIVN / LCID) is the natural next validation step. The prompt's framing block should produce visibly different narrative tone; verify the prose actually adapts. Lands during the 4.8 dogfood gate.
  - **Test fixture matrix** (NVDA / F / RIVN / TBD) deferred — can fold into 4.8 dogfood or a dedicated 4.5.C if we want named-symbol regression coverage.
  - **Bundle headroom** is now 1.63 KB. Phase 4.6 (Compare page) is ~3 KB net, will need either a chunk split for the new route or compression of an existing card. Address in 4.6 specifically.

### 4.5.C Layout polish from dogfood feedback *(this PR)*

> **Why this exists:** the 4.5.B dogfood surfaced four UX issues the
> unit tests couldn't catch — page-level whitespace on big monitors,
> row-internal height mismatch where shorter cards left blank canvas
> below them, ContextBand placement burying the numeric content, and
> "UNAVAILABLE" placeholder cards wasting column slots on cached
> reports. All four are layout-shape issues, not data correctness;
> shipping them in 4.5.C keeps 4.5.B's behavioral diff reviewable
> separately from this surface refresh.

- [x] **Container width** — SymbolDetailPage's `max-w-6xl` (1152px) → `max-w-screen-2xl` (1536px). Padding shrinks from `px-8` to `px-6` on small breakpoints, growing back to `lg:px-8 / xl:px-10` on bigger ones to keep content from hugging the edges. Dashboards now breathe at 1920px+ resolutions while staying readable at 1280px.
- [x] **`items-start` on every multi-column grid** — cards render at natural height with honest gaps below shorter cards rather than stretching to row height. Option (b) from the user's choice — adapts to different resolutions because the gap "absorbs" the height difference.
- [x] **ContextBand moved to bottom** — Business + News now render after row 4 (and before the trailing ReportRenderer fallback) instead of between hero and row 2. Hero → row 2 → row 3 → row 4 → ContextBand keeps numeric content up top.
- [x] **Auto-collapse row 4 to N columns** — RiskDiffCard + MacroPanel return `null` instead of placeholder "UNAVAILABLE" cards. SymbolDetailPage's row 4 grid uses `lg:grid-cols-{1,2,3}` based on a populated-card count. Cash + Risk + Macro on healthy data; Cash alone fills the row width when Risk and Macro are empty. `data-card-count` attribute exposed for regression tests.
- [x] **DashboardRows extracted** from SymbolDetailPage's main render for readability. The IIFE in 4.5.B was inline; refactoring it to a named subcomponent kept the parent component's JSX scannable.
- [x] **Tests** — 387 → **392** frontend (+5 net: 5 new SymbolDetailPage layout assertions; 2 placeholder-render tests on RiskDiffCard / MacroPanel flipped to null-return assertions). Backend untouched at 607.
- [x] **Bundle** — main 98.37 → **98.42 KB gz** (+0.05). Headroom unchanged at ~1.58 KB.
- [x] **Update test counts** — backend stays at 607, frontend 387 → **392**. Updated in `CLAUDE.md`, `docs/architecture.md`, this file.

### 4.5.C review *(filled in after the GREEN + docs commits land)*

- **What changed in shape:** one container className change. One `items-start` class added to every grid (5 grids). One subcomponent extraction (DashboardRows). Two `if !data return null` branches added to RiskDiffCard / MacroPanel. ContextBand moved one position. No new components, no new dependencies, no schema changes.
- **What didn't change:** healthy reports' card content. The new auto-collapse is back-compat: a section that returns 4 claims renders the same RiskDiffCard as before; a section with 0 claims used to render a placeholder, now renders nothing — and the surrounding row picks a tighter grid.
- **Net deltas:** backend zero; frontend +5 tests / 2 cards null-return / 1 IIFE → DashboardRows refactor / 1 grid-cols-N column count switch; main bundle +0.05 KB gz.
- **Followups noted:**
  - The Vite HMR cache wasn't picking up file changes during preview verification (same issue as 4.5.B). Tracked as: when the worktree is in `.claude/worktrees/...`, Vite's file watcher misses mtime updates. Workaround: trust unit tests; rely on `vite build` to verify production rendering. Long-term fix: investigate whether `server.watch.usePolling` in `vite.config.ts` would resolve.
  - Bundle headroom still ~1.58 KB. Phase 4.6 Compare page will need a chunk split for the new route. Plan to use `React.lazy()` on the `/compare` route component so the bundle bills only get hit when the user navigates there.

### 4.6 Compare page *(NEXT — pickup-ready)*

> **Why this is next:** the symbol dashboard answers "is this name distressed / healthy / overvalued?" in isolation, but the natural follow-up is "vs what?" A side-by-side compare page reuses every Phase 4 card primitive against two reports at once. Strata mockup at `docs/screenshots/image-1777831012413.png` shows the target shape.
>
> **Bundle note:** main bundle is at 98.42 KB gz with ~1.58 KB headroom. Compare page is a new route — easiest path is `React.lazy(() => import("./components/ComparePage"))` so the entire 4.6 deliverable lives in its own chunk and only the route tree node is in main. Pattern already exists for `SectionChart` in `frontend/src/components/ReportRenderer.tsx`.

**Frontend:**

- [ ] **`/compare?a=NVDA&b=AVGO`** route — two-ticker side-by-side dashboard, lazy-loaded. Read both tickers from the query string, uppercase both, fire two `fetchResearchReport` queries in parallel via `useQueries` from TanStack Query.
- [ ] **`CompareHero`** — two ticker cards side-by-side with mini price charts in the subject's accent color (NVDA cyan, AVGO violet say). "VS" indicator between them. Reuses existing `LineChart` primitive (likely `width="100%"` with `showAxes={false}`).
- [ ] **`CompareValuationRow`** — 4 metrics (P/E forward, P/S, EV/EBITDA, PEG) shown as horizontal bars between the two values with "lower = cheaper" hint. Build on the Valuation cell pattern from `valuation-extract.ts` — extract the 4 metric values per ticker, render two-stop bars.
- [ ] **`CompareQualityRow`** — 4 metrics (Gross margin, Operating margin, FCF margin, ROIC) with horizontal bars. Mirror of the valuation row.
- [ ] **`CompareMarginOverlay`** — 20Q operating margin both tickers on shared axes via `MultiLine` primitive. Single chart, two series. Narrative call-out below ("NVDA's operating margin overtook AVGO's in Q2-23"). The narrative copy is LLM-generated — pass both tickers' Quality sections to a new `compose_compare_narrative` synth call (or defer narrative to 4.6.B if Sonnet integration adds risk).
- [ ] **`CompareGrowthOverlay`** — 5Y per-share growth, both rebased to 100, both tickers on shared axes. Same pattern as `MultiLine` but with rebase logic from `growth-extract.ts`.
- [ ] **`CompareRiskDiff`** — both tickers' 10-K risk paragraph deltas as parallel bar charts. Reuse the per-category bar logic from `RiskDiffCard`'s `CategoryBars`.
- [ ] **"What's cut" footer** — explicitly lists what doesn't appear in compare mode (Macro, full Business descriptions, News). Honest about scope.
- [ ] **Add ticker / Swap controls** — top-right. "Add ticker" pops a search modal; "Swap" exchanges `?a=` and `?b=`.

**Backend (only if compare narrative ships):**

- [ ] **`POST /v1/compare?a=NVDA&b=AVGO`** OR fold compare narrative into existing `POST /v1/research/{symbol}` with a `?compare_to=AVGO` query string. Decision: if the narrative is just one synth call against both reports' claims joined, no new endpoint needed — the frontend can fetch both reports and pass them to a new `compose_compare_narrative` orchestrator function via a thin `POST /v1/compare/narrative` route. Skip if it's too much for one PR; the visual compare can ship without a narrative call-out.

**Tests:**

- [ ] Frontend ~12 new tests across the new components. Backend ~3 if the compare-narrative endpoint ships.
- [ ] **No new test fixtures for live LLM** — use the existing `_summaries_for` pattern in `tests/test_research_orchestrator.py` style.

**Implementation notes:**

- The 4.5.A `LayoutSignals` work doesn't apply on the compare page — distress flags are per-ticker. If both tickers are distressed (Rivian vs Lucid), fine; if only one is, render the distress chrome on that ticker's column only. Keep it simple: just pass each ticker's `layout_signals` to its column's HeroCard and let the existing distress logic activate per-side.
- Path of least bundle resistance: ComparePage and ALL its sub-components (`CompareHero`, `CompareValuationRow`, `CompareMarginOverlay`, etc.) live in one file or one `compare/` subdirectory, lazy-loaded as a unit. Don't lazy-load each sub-component individually — that fragments the chunk graph for no gain.

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
