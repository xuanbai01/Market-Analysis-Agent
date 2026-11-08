# Dogfood — 2026-11 (Phase 4.8, deployed stack)

Production: https://market-analysis-agent-red.vercel.app → https://market-analysis-agent.fly.dev, `LLM_PROVIDER=deepseek` (`deepseek-flash`). Findings in the order hit; severity is how much a reader could be misled or blocked.

## Setup issues (fixed during the session)

- **Fly never had an LLM key.** Only `DATABASE_URL` was set, so production could never generate a report; the cached April/May reports came from local runs whose `.env` pointed at Neon. Now `BACKEND_SHARED_SECRET` + `DEEPSEEK_API_KEY` are secrets and `FRONTEND_ORIGIN` / `LLM_PROVIDER` live in `fly.toml` (#72).
- **First report: 503 "DeepSeek API returned HTTP 401"** for the key ending `d2af`. The local `.env` held the same revoked key (DeepSeek's free `/models` endpoint also 401'd it). A fresh key (`…0ae2`, `/models` → 200) was piped to Fly from `.env`.

## AAPL — first successful live report (2026-11-08)

Generated in ~20 s. Every card rendered: hero + price chart, Quality rings + margins, Earnings 19/20 beats + recent prints, Valuation matrix + peer scatter, per-share growth, Cash & capital, 10-K risk diff with per-category bars, Business, **News (17 categorized headlines — #69 works in production)**, Capital Allocation.

| # | Severity | Finding | Root cause / note |
|---|---|---|---|
| 1 | **High** | Section prose cites raw stored values instead of display units: "return on equity of 1.42", "net profit margin of 0.276", card strip "ROE 1.42 and ROIC 0.65". Worse, Capital Allocation says "a buyback yield of 0.017 against a forward dividend yield of 0.32" — reads as dividend > buyback, but the data is buyback 1.74% vs dividend 0.32%. | `research_orchestrator._format_claim_line` sends `repr(value)` with no unit; `Claim.unit` (4.3.X) never reaches the LLM. `dividendYield` is stored percent-form, `buyback_yield` as a fraction, so raw numbers aren't comparable. Sonnet presumably converted by habit; DeepSeek copies what it's given. **Fixed in #74:** prompt lines carry the dashboard's display value (`Return on equity = 142.26%`); live AAPL now reads "ROE of 142.26%" and "Buybacks outpace the dividend. 1.74% buyback yield versus a 0.32% forward yield" (factuality 0.989). |
| 2 | Low | Loading copy reads "Generating report for loading…" — the ticker slot shows the name placeholder. | Frontend `LoadingState` text. |
| 3 | Low | Business card renders the full multi-paragraph yfinance summary; the 4.4.A spec said ~3 lines with overflow. | `BusinessCard` truncation. |
| 4 | Info | Per-share growth spans only 4 quarters (multipliers all ~1.1×), so the card says little. | yfinance quarterly statements only go back ~5 quarters; longer history would need annual data or XBRL (Phase 6). |
| 5 | Info | News categories skew to OTHER (3 of the first 5). | DeepSeek categorizer; check across more tickers before tuning. |
| 6 | Low | Gross-margin YoY change shows as "up 1.88%" (card and prose); it's 1.88 percentage points. | `gross_margin_trend_1y` is annotated `fraction`; a points-style unit would be more precise. |
| 7 | — | Rate limit (3 fresh reports/IP/hour) blocked dogfooding. | Raised to 30/h for the dogfood phase in `fly.toml` (#73); lower before sharing publicly. |

## NVDA — chart readability (owner review, 2026-11-08)

> "No baseline, no process shown — the chart has no head or tail; I can't read it."

| # | Severity | Finding | Root cause / note |
|---|---|---|---|
| 8 | **High** | Per-share growth chart can't be read: no y-axis or values, the "= 100" baseline isn't drawn, only first/last quarter labelled, no data points, no hover. FCF/OCF draw a smooth hill whose shape between quarters is invented. | `MultiLine`: three unlabeled grid lines (middle one dashed), Catmull-Rom smoothing, first/last x-labels only, no markers/tooltip. Rebasing to the first quarter also exaggerates small bases (NVDA FCF base $0.55 → "3.6×" peak) and inverts direction when the base is negative (RIVN-class FCF). All five series are $/share already, so they can share one real axis without rebasing. |
| 9 | Medium | Cash & capital mini charts (80 px, no scale, 10 px labels) show flat lines; CapEx $0.11 vs SBC $0.08, or debt tripling to $1.58, aren't readable. | Two `MultiLine`s at 80 px with `showLegend={false}`. These are "current value + trend" data — stat tiles fit better. |
| 10 | Medium | Quality table trend cells imply trends the data can't support: ROIC/ROE have only 2 points, so the "falling" line is two dots joined; min–max autoscaling makes a 3-pt move look like a crash. | `Sparkline` autoscale, no endpoint markers, no stated change, no minimum point count. |

**Redesign — approved and built in #75** (verified on a local NVDA report at 800 and 1440 px: labels a true 11 px, 0 clipped, 0 overlapping):

1. `MultiLine` v2 — y-axis with clean ticks and a solid baseline (0, or 100 when indexed); solid hairline grid; every quarter labelled (thinned past ~8); straight segments with ≥8 px markers; end-of-line value labels with collision nudging; crosshair + tooltip with every series and QoQ change. Used by Quality margins, per-share growth, compare overlays.
2. Per-share growth — actual $/share, split into Income (Rev / GP / OpI) and Cash flow (OCF / FCF) panels on one shared scale; multiplier + CAGR pills unchanged. Handles negative values with the zero baseline.
3. Cash & capital — four stat tiles (value, change vs first quarter, sparkline with marked ends) plus the net-cash tile.
4. Trend cells — marked endpoints + a stated change ("▼ 37.3 pts vs prior quarter"); no line under 3 points ("only 2 quarters of data").
