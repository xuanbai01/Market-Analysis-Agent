# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [ADR 0003](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: free data only, citation discipline non-negotiable. Phase 1 infrastructure complete.
>
> **Product shape:** [ADR 0004](../docs/adr/0004-visual-first-product-shape.md) — visual-first, delta-driven. Multi-year history rendered as charts; LLM commentary stays short. **Not** chasing Morningstar-depth analyst narrative.
>
> **Surface shape:** [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md) — pivot from "click Generate → static report" to **symbol-centric dashboard** (`/symbol/:ticker`) with adaptive layouts. Same backend; new frontend architecture.

## In progress

- **Workstream A (cleanup)** is in review on `chore/roadmap-and-cleanup`. **A2 is next** — see the plan below.

## Plan — after Phase 5 (2026-11-13)

A review on 2026-11-13 found the roadmap exhausted: every phase was shipped or deferred, and the candidates list had no goal ordering it. **Goal for this stretch:** close the oldest open diligence gap (valuation against the company's own history) and make the product something a person other than the owner can see. Order: A → A2 → B → C, then D. One PR per workstream.

### A. Cleanup *(branch `chore/roadmap-and-cleanup`)*

- [x] **Remove the 501 stubs** — `/v1/analysis`, `/v1/reports/daily/latest`, `/v1/forecasts/{symbol}`: the routers, their mounting, the route-auth test's exemption, the doc rows.
- [x] **Remove the unreachable Recharts path** — `SectionChart`, `lib/featured-claim.ts` and the `recharts` dependency. Every section the backend builds has a dedicated card (`CARD_SECTIONS` covers all nine titles in `SECTIONS_BY_FOCUS`), so the chart could never load. `ReportRenderer` stays as a plain claims table for a section that has no card yet: the next backend section shows up there until its card lands.
- [x] **Live eval from GitHub** — `.github/workflows/live-eval.yml`, started by hand. ADR 0004 says the live golden eval gates report changes; until now it only ran on a laptop.
- [x] **Docs** — the per-PR history moves from CLAUDE.md to `docs/changelog.md`; completed phases move from this file to [archive-phases-1-5.md](archive-phases-1-5.md); test counts and bundle sizes are stated once each (`docs/testing.md`, `frontend/README.md`) instead of in six files; stale statements fixed (design_doc tools table and risks row, dogfood item #4).
- [x] **A cyclical through the dashboard** — XOM, 2026-11-13, on a local stack. The layout rules held (XOM is profitable today, so a cyclical in a trough is still untested). It found three data problems, logged as #18–#20 in [dogfood-2026-11.md](dogfood-2026-11.md) and planned as A2.

Owner actions (they need an account or a decision):

- [ ] **`FRED_API_KEY` on Fly** (`fly secrets import`) — without it the Macro card never renders in production.
- [ ] **`DEEPSEEK_API_KEY` as a GitHub Actions secret** — the live-eval workflow needs it.
- [ ] **`docs/screenshots/`** (the Strata mockups the archive links to) is untracked: commit it or delete it.
- [ ] **Branch protection on `main`**, and `ANTHROPIC_API_KEY` as a repo secret for the AI PR review job.

### A2. Fixes from the XOM check *(branch `fix/sec-successor-and-oil-peers`)*

These change report content, so they come before B, which builds on the same SEC history.

- [ ] **Successor registrants** (dogfood #18) — after Exxon's 2026 holding-company reorganization, SEC's ticker map points XOM at a new registrant with no 10-K and no XBRL history, so the risk card and the ten-year view vanish. Resolve a ticker to its filing history across the predecessor registrant too.
- [ ] **A tool that returns nothing is not "ok"** (#18) — `tool_calls_audit` should say empty, and the page should say which sections had no data instead of only showing LOW confidence.
- [ ] **Split the `oil_gas` peer group** (#19) into integrated majors and exploration & production, as consumer staples was split in ADR 0007.
- [ ] **One basis for gross margin** (#20) — the snapshot, the margin chart and the trend cell should agree.
- [ ] **Bump `REPORT_VERSION`** and run the live golden eval; consider adding XOM to the golden set.

### B. Valuation against the company's own history *(branch `feature/valuation-history`)*

ADR 0004 called "is this expensive versus its own history" the most-cited gap; the Valuation card still compares only against peers. The ten-year per-share history (#90) supplies the denominators.

- [ ] **`fetch_valuation_history` tool** (`app/services/valuation_history.py`) — fiscal-year-end price ÷ that year's diluted EPS, revenue per share and FCF per share gives P/E, P/S and P/FCF for up to ten years. Needs ten years of closes (the price route stops at 5Y): split-adjusted but not dividend-adjusted, to match the split-adjusted per-share figures. A loss year has no P/E (P/S still draws). Banks: P/E and P/S only.
- [ ] **Claims** in the Valuation section, with history, plus **derived claims** in `research_derived.py`: the ten-year median of each multiple, today's multiple against that median (premium or discount), and where today sits in the ten-year range. Each description names its basis (fiscal-year multiple vs today's trailing multiple).
- [ ] **Prose and thesis** pick the claims up through the existing claim lines; **bump `REPORT_VERSION`**; live golden eval ≥ 0.97 on all five tickers.
- [ ] **ValuationCard** — an own-history panel: one multiple at a time (P/E · P/S · P/FCF), a yearly line, the median, today marked. Read the dataviz rules before drawing.
- [ ] **Data checks** on KO, NVDA (splits), AAPL (September year end), JPM (bank), RIVN (losses).

### C. Make it showable *(C2 needs the owner's go-ahead on the design before any code)*

- [ ] **C1 README screenshots** — hero + analyst view, one full dashboard, the capex lens. The last attempt found the browser pane only saves small JPEGs; these may need capturing by hand.
- [ ] **C2 Public read-only demo** — design to confirm first: an unauthenticated route that serves the latest cached report for a fixed list of tickers (`DEMO_SYMBOLS`, empty = off), never generates a report and never calls a provider; cached prices for the same tickers; a "View demo" entry on the sign-in page; Regenerate and search hidden in demo mode. `tests/test_route_auth.py` lists the route as deliberately open and `docs/security.md` A01 records it.
- [ ] **C3 Lower `RESEARCH_RATE_LIMIT_PER_HOUR`** from 30 to 3 in `fly.toml`, in the same PR as C2.

### D. After those (unordered)

- [ ] **More lenses** — R&D intensity, SBC ÷ revenue, buybacks vs dividends for the megacap group; `lens.py` and `xbrl.py` generalize. A trailing-12-month point for the partial year is the other open idea.
- [ ] **Insider activity** — `form_4.py` (tested since Phase 2) has never reached the dashboard; a section and a card would serve the catalyst workflow. Decide `holdings_13f.py` at the same time: surface it or delete it.
- [ ] **Split modules past the 400-line convention when next touched** — `research_orchestrator.py` (619), `ten_k.py` (614), `earnings.py` (532), `fundamentals.py` (520).

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
