# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [ADR 0003](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: free data only, citation discipline non-negotiable. Phase 1 infrastructure complete.
>
> **Product shape:** [ADR 0004](../docs/adr/0004-visual-first-product-shape.md) — visual-first, delta-driven. Multi-year history rendered as charts; LLM commentary stays short. **Not** chasing Morningstar-depth analyst narrative.
>
> **Surface shape:** [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md) — pivot from "click Generate → static report" to **symbol-centric dashboard** (`/symbol/:ticker`) with adaptive layouts. Same backend; new frontend architecture.

## In progress

- **Workstream C (public demo)** is in review on `feature/public-demo`. **D is next** (unordered; pick one). A merged as #92, A2 as #93, B as #94.

## Plan — after Phase 5 (2026-11-13)

A review on 2026-11-13 found the roadmap exhausted: every phase was shipped or deferred, and the candidates list had no goal ordering it. **Goal for this stretch:** close the oldest open diligence gap (valuation against the company's own history) and make the product something a person other than the owner can see. Order: A → A2 → B → C, then D. One PR per workstream.

### A. Cleanup ✅ *(#92, merged 2026-11-13)*

- [x] **Remove the 501 stubs** — `/v1/analysis`, `/v1/reports/daily/latest`, `/v1/forecasts/{symbol}`: the routers, their mounting, the route-auth test's exemption, the doc rows.
- [x] **Remove the unreachable Recharts path** — `SectionChart`, `lib/featured-claim.ts` and the `recharts` dependency. Every section the backend builds has a dedicated card (`CARD_SECTIONS` covers all nine titles in `SECTIONS_BY_FOCUS`), so the chart could never load. `ReportRenderer` stays as a plain claims table for a section that has no card yet: the next backend section shows up there until its card lands.
- [x] **Live eval from GitHub** — `.github/workflows/live-eval.yml`, started by hand. ADR 0004 says the live golden eval gates report changes; until now it only ran on a laptop.
- [x] **Docs** — the per-PR history moves from CLAUDE.md to `docs/changelog.md`; completed phases move from this file to [archive-phases-1-5.md](archive-phases-1-5.md); test counts and bundle sizes are stated once each (`docs/testing.md`, `frontend/README.md`) instead of in six files; stale statements fixed (design_doc tools table and risks row, dogfood item #4).
- [x] **A cyclical through the dashboard** — XOM, 2026-11-13, on a local stack. The layout rules held (XOM is profitable today, so a cyclical in a trough is still untested). It found three data problems, logged as #18–#20 in [dogfood-2026-11.md](dogfood-2026-11.md) and planned as A2.

Owner actions (they need an account or a decision):

- [x] **`FRED_API_KEY` on Fly** — set by the owner 2026-11-13. Reports cached before it keep an empty Macro section until they rebuild (the version bump in A2 does that).
- [x] **`DEEPSEEK_API_KEY` as a GitHub Actions secret** — set 2026-11-13; the Live Eval workflow ran on `main` the same day, 5 of 5 at factuality 1.000.
- [ ] **`docs/screenshots/`** (the Strata mockups the archive links to) is untracked: commit it or delete it.
- [ ] **Branch protection on `main`**, and `ANTHROPIC_API_KEY` as a repo secret for the AI PR review job.

### A2. Fixes from the XOM check ✅ *(#93, merged 2026-11-13)*

These change report content, so they come before B, which builds on the same SEC history.

- [x] **Successor registrants** (dogfood #18) — SEC publishes no machine-readable link between a new holding company and the registrant it replaced, so `app/services/sec_registrants.py` keeps the links by hand (XOM so far). The EDGAR provider merges filings across the chain and the XBRL series fill earlier years from the predecessor.
- [x] **Share-count fallback** (#22, found while checking the fix) — Exxon stopped tagging a diluted share count after 2013, which cut its annual history to three years; the combined and basic counts now fill those years.
- [x] **A tool that returns nothing is not "ok"** (#18) — `tool_calls_audit` says `empty`, and the dashboard lists empty and failed tools under the header ("Not in this report: …").
- [x] **Split the `oil_gas` peer group** (#19) — `integrated_oil` (XOM, CVX, SHEL, BP, TTE) and `oil_gas_producers` (COP, OXY, EOG, DVN, FANG).
- [x] **One basis for gross margin** (#20) — the Quality claim is the latest quarter of its own history; Yahoo's trailing figure is a separate Valuation claim that the peer comparison and the scatter use.
- [x] **`REPORT_VERSION` 3**; XOM added to the golden set (six cases).

### B. Valuation against the company's own history ✅ *(#94, merged 2026-11-13)*

ADR 0004 called "is this expensive versus its own history" the most-cited gap; the Valuation card compared only against peers.

- [x] **Year-end multiples** — `fetch_annual_history` also prices each fiscal year (`app/services/valuation_history.py`): the close on the year's last trading day over that year's diluted EPS, revenue per share and FCF per share. Built into the existing tool, not a new one, so one SEC read serves both. Loss years have no earnings multiple; a multiple above 200 is left out; banks get no cash-flow multiple.
- [x] **Claims** — the three series in the Valuation section, plus derived claims: the median of each, today's trailing multiple as a premium or discount to it, and today's price-to-free-cash-flow.
- [x] **Prose and thesis** read them through the existing claim lines. Both prompts gained a rule that a fiscal-year figure is named by its year, after the first report called one "today". `REPORT_VERSION` 4.
- [x] **ValuationCard** — "Against its own history": one small chart per multiple, each on its own scale, the median as a reference line, today at the end of the line. A year more than four times the median is named instead of drawn.
- [x] **Data checks** on KO, NVDA (splits), AAPL (September year end), JPM (bank), RIVN (losses) and XOM (predecessor registrant).

### C. Make it showable *(C2 and C3 on branch `feature/public-demo`, in review)*

- [ ] **C1 README screenshots** — hero + analyst view, one full dashboard, the capex lens. The browser pane only saves small images, so these need capturing by hand (owner).
- [x] **C2 Public read-only demo** — `/demo` and `/v1/demo/*`: the latest stored report and stored prices for the tickers in `DEMO_SYMBOLS`, never a generated report or a provider call. Off unless the setting is non-empty; production lists AAPL, NVDA, KO, JPM, RIVN and XOM.
- [x] **C3 Rate limit** — production `RESEARCH_RATE_LIMIT_PER_HOUR` 30 → 10, not the 3 first planned: generation still needs the secret, and 3 would stop the owner rebuilding more than three tickers an hour after a report-version bump.
- [ ] **After the merge (owner):** open each demo ticker once while signed in, so its report is built at the current version. The demo shows whatever is stored, and a ticker with nothing stored doesn't appear.

### D. After those (unordered)

- [ ] **More lenses** — R&D intensity, SBC ÷ revenue, buybacks vs dividends for the megacap group; `lens.py` and `xbrl.py` generalize. A trailing-12-month point for the partial year is the other open idea.
- [ ] **Insider activity** — `form_4.py` (tested since Phase 2) has never reached the dashboard; a section and a card would serve the catalyst workflow. Decide `holdings_13f.py` at the same time: surface it or delete it.
- [ ] **Predecessor registrants for older reorganizations** — a company that moved to a new registrant years ago still has its 10-Ks, but its ten-year history stops at the move (candidates to check against SEC: DIS 2019, CI 2018, AVGO 2018, CHTR 2016, LIN 2018). Each is one verified line in `sec_registrants.py`; a merger shows up as a share-count jump, which the existing guard cuts at.
- [ ] **Split modules past the 400-line convention when next touched** — `research_orchestrator.py`, `ten_k.py`, `earnings.py`, `fundamentals.py` and `research_derived.py` (the last grew past 500 lines with the own-history claims).

Still deferred, triggers unchanged: Phase 6 (segment and geography mix; needs a filing-level XBRL parser), the 4.6.B compare narrative, the Sonnet comparison run of the golden eval.

## Handoff — pickup notes (2026-11-13)

If you're picking this up after a gap:

1. **Read [CLAUDE.md](../CLAUDE.md) "Current state"**, then the plan above. What shipped and why is in [docs/changelog.md](../docs/changelog.md); what the owner reacted to is in [dogfood-2026-11.md](dogfood-2026-11.md); the phase-by-phase task detail is in [archive-phases-1-5.md](archive-phases-1-5.md).
2. **Production:** dashboard <https://market-analysis-agent-red.vercel.app>, API <https://market-analysis-agent.fly.dev>, `LLM_PROVIDER=deepseek`. A push to `main` deploys both; the owner sets Fly secrets ([docs/deployment.md](../docs/deployment.md) §7). A change to report content bumps `REPORT_VERSION`, and cached reports rebuild on their next visit.
3. **Test counts and bundle sizes:** [docs/testing.md](../docs/testing.md) and [frontend/README.md](../frontend/README.md) are the only places that state them.

**Known minor issues:**

- **Vite HMR cache misses file mtime in `.claude/worktrees/...`** — see [lessons.md](lessons.md). Workaround: trust unit tests + `vite build`; fix candidate `server.watch.usePolling: true`.
- **Cancel-on-navigate** (old Bug 8): leaving a ticker page mid-generation doesn't abort the request. Hasn't bitten in dogfood.
- **Help overlay (`?` shortcut)** — still deferred; ⌘K is the only shortcut.
- **The EDGAR disk cache never looks for a newer filing** once it holds as many as a call asks for (`edgar._try_cache`): a machine that cached two 10-Ks keeps serving them after a third is filed. Fly's disk is wiped on every stop, so production recovers by itself; a long-lived local `.edgar_cache` does not. Found 2026-11-13, not fixed.
- **Yahoo's `info` can come back partial.** One KO fetch on 2026-11-13 had no price-to-sales, EV/EBITDA or gross margin; the report then shows "—" in those cells and "no trailing figure today" on two own-history panels until it is regenerated. A retry, or a fallback from the latest close and trailing per-share figures, would fix it. Not fixed.
- **Alphabet's annual history starts in 2022.** Before then it tagged share counts per share class, which the SEC company-concept API doesn't return, so GOOGL has four years of per-share figures and multiples. The same limit applies to any company that reports shares only by class.
- **Left from the 2026-11-13 security review of the demo** (low severity, not fixed): `app/core/logging.py` is never imported, so the `app.external` call log may not be written in production (unverified); two requests arriving as a demo cache entry expires each query the database once; `tool_calls_audit` (tool names and exception class names) is public on demo reports, which was accepted.
- **XBRL revenue tags can mix definitions across years.** `xbrl.annual_series` takes the first tag that has a year, and XOM's 2017–2021 revenue comes from a narrower tag than the years around it (about 3% lower). The ends of its ten-year series are on one tag, so the growth rate is unaffected. Found 2026-11-13, not fixed.

**[lessons.md](lessons.md)** — read before non-trivial work to avoid retreading earlier mistakes.

## Local-dev gotchas (Windows)

A clean checkout on Windows often hits two issues that cost dev hours if not pre-warned:

1. **Native Postgres 18 service collides with Docker's :5432 mapping.** When the Windows `postgresql-x64-18` service is running, Docker's `5432:5432` mapping silently bumps the host port. Check with `docker ps` — if you see `0.0.0.0:5433->5432/tcp`, update `.env`'s `DATABASE_URL` to `localhost:5433`. Alternative: `Stop-Service postgresql-x64-18` to free :5432, then `docker compose down && up -d db`.
2. **`.env`'s `DATABASE_URL` defaults to whatever the previous user set.** If the alembic / uvicorn stack hangs forever or fails with `ConnectionRefusedError`, check whether the URL points at Neon (`...neon.tech...?sslmode=require`) when you meant local. Neon connections appear in stack traces as `_create_ssl_connection`. Replace with `postgresql+asyncpg://postgres:postgres@localhost:5432/marketdb` for local.

## Phase 6 — XBRL Tier 2 (deferred; the 4.8 gate did not ask for it)

> **Deferred** — the 4.8 dogfood never asked for segment / geography / RPO breakdowns. There are no placeholder cards for them (an earlier plan had some; they never shipped, and cards with no data render nothing). The lens work added `app/services/xbrl.py` (company-concept API, tag merging, calendar frames), which is the starting point (it now also feeds the ten-year per-share history, `app/services/annual_history.py`); segment data lives in dimensional XBRL facts that API doesn't return, so this still needs a filing-level parser. If users repeatedly note the gap (especially for names where segment mix is the story — NVDA Data Center vs Gaming, AMZN AWS vs Retail), escalate.

- [ ] **XBRL parser** — pick `python-xbrl` or `arelle`; reuse `fetch_edgar`'s polite-crawl + disk-cache infrastructure. One-time effort; pays for itself across all SEC filers.
- [ ] **`fetch_segments` (new tool)** — parses `us-gaap:SegmentReportingDisclosure` from the latest 10-K + every 10-Q since. Returns revenue + operating income time series per reportable segment.
- [ ] **`fetch_geographic_revenue` (new tool)** — parses geographic-disaggregation tags. Returns revenue time series by region (US / Taiwan / China / etc., per the company's reporting structure — no normalization).
- [ ] **`fetch_rpo_history` (new tool, conditional)** — `us-gaap:RevenueRemainingPerformanceObligation` + `RemainingPerformanceObligationExpectedTimingOfSatisfactionPercentage` for the NTM%. Renders only when the company reports it (mostly SaaS / subscription / defense).
- [ ] **Frontend additions** — `SegmentDonut` (TTM share) + `SegmentTimeSeries` + `GeographyDonut` + `GeographyTimeSeries` + `RPOCard` rendered into the Phase 4.4 ContextBand placeholders.

## Other deferred Phase 3 work (rolled forward; revisit case-by-case)

These were sketched during Phase 3 but never landed; either Phase 4 absorbs them (news, price history) or they stay deferred:

- [x] **News in report** — absorbed into Phase 4.4 (NewsList component + Haiku categorization).
- [ ] **`fetch_valuation_history` (new derived tool)** — multiples over time with a median. *(Now workstream B in the plan above, built on the ten-year per-share history from #90.)*
- [ ] **`fetch_dividends_history` (new tool, conditional)** — yfinance `Ticker.dividends` for quarterly history; would unlock a `DividendsCard`. *(Still deferred — niche to dividend payers. Revisit if a recurring use case surfaces.)*
- [ ] **Price-and-technicals history** — partially absorbed into Phase 4.0/4.1 (60-day price chart in hero). Full SMA / RSI overlay and 5Y price view still TBD; revisit if Phase 4.8 dogfooding shows demand.

## Future scope (deliberately deferred — revisit when there's a concrete trigger)

- [ ] **`search_history`** — pgvector RAG over stored news + filings. Was the original "Phase 3" sketch in ADR 0003. Demoted by ADR 0004 because it doesn't address the perceived-shallowness gap. Revisit if a recurring eval query genuinely benefits from semantic search across our corpus.
- [ ] **`compute_options`** — yfinance options chain → IV percentile, implied move. Was the other half of the original "Phase 3" sketch. Demoted similarly. Revisit if Phase 4's Catalyst section needs implied-move framing.
- [ ] **LLM-driven section composition** (was 2.2d) — replace the static `SECTION_TO_CLAIM_KEYS` map with LLM triage. No signal yet that the deterministic catalog is too rigid.
- [ ] **Supervisor mode** (was 2.3) — multi-symbol comparative queries via specialist sub-agents. No signal that it adds factuality / structure benefit over the single-agent default.
- [ ] **Reddit / r/wallstreetbets sentiment** — narrow signal, high noise. Per ADR 0003 cut from must-have.
- [ ] **Discord bot client** — was original v1 vision; deferred indefinitely.
- [ ] **Real-time / 15-min scheduled ingest, Celery, Redis** — cut by ADR 0003.
- [ ] **Real auth + per-user cost caps + abuse logging** — only when there are real users. Phase 3.0's shared-secret gate is enough until then.

## Blocked / waiting

-
