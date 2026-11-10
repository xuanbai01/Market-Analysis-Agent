# Dogfood — 2026-11 (Phase 4.8, deployed stack)

Production: https://market-analysis-agent-red.vercel.app → https://market-analysis-agent.fly.dev, `LLM_PROVIDER=deepseek` (`deepseek-flash`). Findings in the order hit; severity is how much a reader could be misled or blocked.

## Setup issues (fixed during the session)

- **Fly never had an LLM key.** Only `DATABASE_URL` was set, so production could never generate a report; the cached April/May reports came from local runs whose `.env` pointed at Neon. Now `BACKEND_SHARED_SECRET` + `DEEPSEEK_API_KEY` are secrets and `FRONTEND_ORIGIN` / `LLM_PROVIDER` live in `fly.toml` (#72).
- **First report: 503 "DeepSeek API returned HTTP 401"** for the key ending `d2af`. The local `.env` held the same revoked key (DeepSeek's free `/models` endpoint also 401'd it). A fresh key (`…0ae2`, `/models` → 200) was piped to Fly from `.env`.

## AAPL — first successful live report (2026-11-08)

Generated in ~20 s. Every card rendered: hero + price chart, Quality rings + margins, Earnings 19/20 beats + recent prints, Valuation matrix + peer scatter, per-share growth, Cash & capital, 10-K risk diff with per-category bars, Business, **News (17 categorized headlines — #69 works in production)**, Capital Allocation.

| # | Severity | Finding | Root cause / note |
|---|---|---|---|
| 1 | **High** | Section prose cites raw stored values instead of display units: "return on equity of 1.42", "net profit margin of 0.276", card strip "ROE 1.42 and ROIC 0.65". Worse, Capital Allocation says "a buyback yield of 0.017 against a forward dividend yield of 0.32" — reads as dividend > buyback, but the data is buyback 1.74% vs dividend 0.32%. | `research_orchestrator._format_claim_line` sends `repr(value)` with no unit; `Claim.unit` (4.3.X) never reaches the LLM. `dividendYield` is stored percent-form, `buyback_yield` as a fraction, so raw numbers aren't comparable. Sonnet presumably converted by habit; DeepSeek copies what it's given. **Fixed in #74 (merged 2026-11-08):** prompt lines carry the dashboard's display value (`Return on equity = 142.26%`); live AAPL now reads "ROE of 142.26%" and "Buybacks outpace the dividend. 1.74% buyback yield versus a 0.32% forward yield" (factuality 0.989). |
| 2 | Low | Loading copy reads "Generating report for loading…" — the ticker slot shows the name placeholder. | Frontend `LoadingState` text. **Fixed in #78:** the route fallback shows the skeleton only. |
| 3 | Low | Business card renders the full multi-paragraph yfinance summary; the 4.4.A spec said ~3 lines with overflow. | `BusinessCard` truncation. **Fixed in #78:** clamps to 3 lines with Show more. |
| 4 | Info | Per-share growth spans only 4 quarters (multipliers all ~1.1×), so the card says little. | yfinance quarterly statements only go back ~5 quarters; longer history would need annual data or XBRL (Phase 6). |
| 5 | Info | News categories skew to OTHER (3 of the first 5). | DeepSeek categorizer; check across more tickers before tuning. |
| 6 | Low | Gross-margin YoY change shows as "up 1.88%" (card and prose); it's 1.88 percentage points. | `gross_margin_trend_1y` is annotated `fraction`; a points-style unit would be more precise. **Fixed in #78:** new `percentage_points` unit, "+1.88 pts". |
| 7 | — | Rate limit (3 fresh reports/IP/hour) blocked dogfooding. | Raised to 30/h for the dogfood phase in `fly.toml` (#73, merged 2026-11-08); lower before sharing publicly. |

## NVDA — chart readability (owner review, 2026-11-08)

> "No baseline, no process shown — the chart has no head or tail; I can't read it."

| # | Severity | Finding | Root cause / note |
|---|---|---|---|
| 8 | **High** | Per-share growth chart can't be read: no y-axis or values, the "= 100" baseline isn't drawn, only first/last quarter labelled, no data points, no hover. FCF/OCF draw a smooth hill whose shape between quarters is invented. | `MultiLine`: three unlabeled grid lines (middle one dashed), Catmull-Rom smoothing, first/last x-labels only, no markers/tooltip. Rebasing to the first quarter also exaggerates small bases (NVDA FCF base $0.55 → "3.6×" peak) and inverts direction when the base is negative (RIVN-class FCF). All five series are $/share already, so they can share one real axis without rebasing. |
| 9 | Medium | Cash & capital mini charts (80 px, no scale, 10 px labels) show flat lines; CapEx $0.11 vs SBC $0.08, or debt tripling to $1.58, aren't readable. | Two `MultiLine`s at 80 px with `showLegend={false}`. These are "current value + trend" data — stat tiles fit better. |
| 10 | Medium | Quality table trend cells imply trends the data can't support: ROIC/ROE have only 2 points, so the "falling" line is two dots joined; min–max autoscaling makes a 3-pt move look like a crash. | `Sparkline` autoscale, no endpoint markers, no stated change, no minimum point count. |

**Redesign — approved, built in #75, merged 2026-11-08** (verified on a local NVDA report at 800 and 1440 px: labels a true 11 px, 0 clipped, 0 overlapping):

1. `MultiLine` v2 — y-axis with clean ticks and a solid baseline (0, or 100 when indexed); solid hairline grid; every quarter labelled (thinned past ~8); straight segments with ≥8 px markers; end-of-line value labels with collision nudging; crosshair + tooltip with every series and QoQ change. Used by Quality margins, per-share growth, compare overlays.
2. Per-share growth — actual $/share, split into Income (Rev / GP / OpI) and Cash flow (OCF / FCF) panels on one shared scale; multiplier + CAGR pills unchanged. Handles negative values with the zero baseline.
3. Cash & capital — four stat tiles (value, change vs first quarter, sparkline with marked ends) plus the net-cash tile.
4. Trend cells — marked endpoints + a stated change ("▼ 37.3 pts vs prior quarter"); no line under 3 points ("only 2 quarters of data").

## Owner reviews after #75 (2026-11-08 → 2026-11-09)

| # | Severity | Finding | Root cause / fix |
|---|---|---|---|
| 11 | Medium | Sidebar "is bad": five unlabeled glyphs, no way home, Watchlist and Recent both just opened Search, Compare opened a pair it didn't name, Export was dead, badges went stale. | **#76** — rewritten around "where can I go" (Search · Home · Compare naming its pair · Lenses) and "what was I looking at" (live Watchlist / Recent via `useSyncExternalStore`); links navigate, buttons act; collapses to a rail. |
| 12 | Wish | Headline markets (S&P 500, Nasdaq 100, Dow, VIX, fear & greed …) at the top of every page. | **#77** — `MarketStrip` + `GET /v1/market/overview`. CNN's fear & greed endpoint refuses automated clients (HTTP 418), so the chip is our own estimate from 4 of CNN's 7 indicators, labelled "est." (owner's choice). |
| 13 | Medium | Cached reports keep pre-fix prose for up to 7 days (AAPL still read "ROE of 1.42" after #74) with no way to refresh from the UI. | **#78** — "Generated 2 days ago · Regenerate" above the hero. |
| 14 | Medium | One card meeting data it can't draw unmounts the whole app (white screen). | **#78** — error boundaries per card, per page, and silent for the strip; unknown claim units parse as null. |
| 15 | **High** | KO: the cards "just display data" — the Quality prose listed the four margins the card already shows. Owner asked for analysis, and for cross-company depth: not just what big-tech capex is, but how it's distributed and what that means. | The prompt carried only current values, no comparisons, and asked for a summary; any comparison the model computed itself failed the rubric. **#79** (ADR 0007) — derived comparison claims computed in code, history in the prompt, interpretive instructions, branded-staples peers for KO (was WMT/COST). **#80** — cited analyst view (bull / bear / changed / watch). **#81** — the megacap capex lens from SEC XBRL. |
| 16 | **High** | First live analyst-view run: NVDA turned news headlines about an investigation into its CEO into a bear point, citing risk-paragraph counts as evidence. | **#80** — news excluded from analyst-view inputs; a cited claim counts only if the point quotes one of its values at the quoted precision. |
| 17 | Medium | KO: cards uneven — a long card beside a short one leaves gaps, some don't line up, the Cash/Risk row had an empty third column. | **#82** — big cards full width with two internal columns; one equal-height row of small cards counting only cards that render (the empty column was Macro reserving a slot with all-None data); new Capital returns card; sticky section nav. KO page 5,978 → 4,952 px. |

**Live golden eval** (DeepSeek Flash; AAPL, NVDA, RIVN, JPM, KO): factuality 1.000 on all five across three runs during #80, the last with the citation check (621 numbers in the prose, none unmatched).

## Coverage and the gate

- **Tickers exercised:** AAPL, MSFT (fresh live reports); NVDA, AVGO, KO, RIVN (dashboard, local and live); JPM (live golden eval: the bank path); plus the seven lens companies. That spans healthy mega-cap, growth, distressed, dividend payer and bank. **Not covered: a cyclical** (CAT, XOM) — check one the next time report generation changes.
- **Open info items:** #4 (per-share growth spans ~5 quarters — yfinance's limit; longer history would come from XBRL, which the lenses now use) and #5 (news categories skew to OTHER) are unchanged.
- **Decision gate (Phase 5 vs 6):** the recurring signal was #15 — "show me what it means", plus cross-company depth — which is the Phase 5 narrative layer. It shipped as ADR 0007 (#79–#81). Nobody asked for segment or geography breakdowns, so Phase 6 stays deferred.
