# Dogfood — 2026-11 (Phase 4.8, deployed stack)

Production: https://market-analysis-agent-red.vercel.app → https://market-analysis-agent.fly.dev, `LLM_PROVIDER=deepseek` (`deepseek-flash`). Findings in the order hit; severity is how much a reader could be misled or blocked.

## Setup issues (fixed during the session)

- **Fly never had an LLM key.** Only `DATABASE_URL` was set, so production could never generate a report; the cached April/May reports came from local runs whose `.env` pointed at Neon. Now `BACKEND_SHARED_SECRET` + `DEEPSEEK_API_KEY` are secrets and `FRONTEND_ORIGIN` / `LLM_PROVIDER` live in `fly.toml` (#72).
- **First report: 503 "DeepSeek API returned HTTP 401"** for the key ending `d2af`. The local `.env` held the same revoked key (DeepSeek's free `/models` endpoint also 401'd it). A fresh key (`…0ae2`, `/models` → 200) was piped to Fly from `.env`.

## AAPL — first successful live report (2026-11-08)

Generated in ~20 s. Every card rendered: hero + price chart, Quality rings + margins, Earnings 19/20 beats + recent prints, Valuation matrix + peer scatter, per-share growth, Cash & capital, 10-K risk diff with per-category bars, Business, **News (17 categorized headlines — #69 works in production)**, Capital Allocation.

| # | Severity | Finding | Root cause / note |
|---|---|---|---|
| 1 | **High** | Section prose cites raw stored values instead of display units: "return on equity of 1.42", "net profit margin of 0.276", card strip "ROE 1.42 and ROIC 0.65". Worse, Capital Allocation says "a buyback yield of 0.017 against a forward dividend yield of 0.32" — reads as dividend > buyback, but the data is buyback 1.74% vs dividend 0.32%. | `research_orchestrator._format_claim_line` sends `repr(value)` with no unit; `Claim.unit` (4.3.X) never reaches the LLM. `dividendYield` is stored percent-form, `buyback_yield` as a fraction, so raw numbers aren't comparable. Sonnet presumably converted by habit; DeepSeek copies what it's given. Fix: send the display value (e.g. `142.26% [fraction 1.4226]`) — the rubric's fraction→percent rule already accepts it. |
| 2 | Low | Loading copy reads "Generating report for loading…" — the ticker slot shows the name placeholder. | Frontend `LoadingState` text. |
| 3 | Low | Business card renders the full multi-paragraph yfinance summary; the 4.4.A spec said ~3 lines with overflow. | `BusinessCard` truncation. |
| 4 | Info | Per-share growth spans only 4 quarters (multipliers all ~1.1×), so the card says little. | yfinance quarterly statements only go back ~5 quarters; longer history would need annual data or XBRL (Phase 6). |
| 5 | Info | News categories skew to OTHER (3 of the first 5). | DeepSeek categorizer; check across more tickers before tuning. |
