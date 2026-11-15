# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [ADR 0003](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: free data only, citation discipline non-negotiable. Phase 1 infrastructure complete.
>
> **Product shape:** [ADR 0004](../docs/adr/0004-visual-first-product-shape.md) — visual-first, delta-driven. Multi-year history rendered as charts; LLM commentary stays short. **Not** chasing Morningstar-depth analyst narrative.
>
> **Surface shape:** [ADR 0005](../docs/adr/0005-symbol-centric-dashboard.md) — pivot from "click Generate → static report" to **symbol-centric dashboard** (`/symbol/:ticker`) with adaptive layouts. Same backend; new frontend architecture.

## In progress

- **Options page: clarity and positioning** (plan below), PR 2 on `feature/options-clarity`.
- **tastytrade, PR A** merged (#116); its review follow-up is on `fix/tastytrade-probe-robustness`. **Owner:** create the OAuth app and set the Fly secrets (deployment.md §9); then the probe runs during a session. Plan below.
- **Options analysis:** the plan's five PRs and the edge-case review are merged (#109–#115). Follow-ups below.

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
- [ ] **Branch protection on `main`.**
- [x] **AI PR review on DeepSeek** *(#97)* — the Claude Code Action needed an `ANTHROPIC_API_KEY` that was never set, so it passed having reviewed nothing. `scripts/ai_review.py` sends the diff to DeepSeek with the `DEEPSEEK_API_KEY` secret already set for the Live Eval and keeps one PR comment.

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

### C. Make it showable *(C2 and C3 merged as #95)*

- [ ] **C1 README screenshots** — hero + analyst view, one full dashboard, the capex lens. The browser pane only saves small images, so these need capturing by hand (owner).
- [x] **C2 Public read-only demo** — `/demo` and `/v1/demo/*`: the latest stored report and stored prices for the tickers in `DEMO_SYMBOLS`, never a generated report or a provider call. Off unless the setting is non-empty; production lists AAPL, NVDA, KO, JPM, RIVN and XOM.
- [x] **C3 Rate limit** — production `RESEARCH_RATE_LIMIT_PER_HOUR` 30 → 10, not the 3 first planned: generation still needs the secret, and 3 would stop the owner rebuilding more than three tickers an hour after a report-version bump.
- [x] **After the merge:** open each demo ticker once while signed in, so its report is built at the current version. The demo shows whatever is stored, and a ticker with nothing stored doesn't appear. Done at `REPORT_VERSION` 8 on 2026-11-15; repeat after each version bump.

### D. After those (unordered)

- [x] **More lenses** *(#103)* — the lens takes a metric (`lens_catalog.py`), and the megacap group has stock-based compensation and R&D lenses beside capex. Checked against SEC first: SBC is tagged by all seven companies every year 2015–2025; R&D by all but Amazon, which reports technology and infrastructure spending instead, so the R&D lens leaves it out and says so.
- [ ] **Buybacks vs dividends lens** — not built: Amazon and Tesla tag neither, Alphabet and Meta started dividends recently, and a missing value can't be told apart from a zero. Needs a rule for "no tag means $0" checked company by company. A trailing-12-month point for the partial year is the other open lens idea.
- [x] **Insider activity** *(#96)* — `form_4.py` rewritten into `fetch_insider_activity`: officer and director purchases and sales over six months, 10% holders apart, the share sold under 10b5-1 plans, the top traders; an Insider Activity section (`REPORT_VERSION` 5) and a full-width card. `holdings_13f.py` stays unsurfaced: 13F holdings are quarterly and 45 days stale, a weaker signal than Form 4s; decide again if someone asks who the big holders are.
- [x] **Predecessor registrants for older reorganizations** *(#98)* — checked against SEC: DIS (← TWDC Enterprises 18, 2019), CI (← Cigna Holding, 2018) and AVGO (← Broadcom Ltd, 2018 ← Avago, 2016) now link back and get their eleventh annual point (2015). The gap was one year, not the whole history: a new registrant's first 10-K carries a few years back. CHTR needed nothing (the ticker resolves to the registrant with 10-Ks back to 2000); LIN neither (the Praxair–Linde share-count jump cuts its history at 2019 whichever registrant holds it).
- [ ] **Split modules past the 400-line convention when next touched** — `research_orchestrator.py`, `ten_k.py`, `earnings.py`, `fundamentals.py` and `research_derived.py` (the last grew past 500 lines with the own-history claims). The Yahoo retry went into its own `yahoo_info.py` rather than grow `fundamentals.py`; peers still read Yahoo's `info` without it.

Still deferred, triggers unchanged: Phase 6 (segment and geography mix; needs a filing-level XBRL parser), the 4.6.B compare narrative, the Sonnet comparison run of the golden eval.

## Plan — options analysis (2026-11-15, [ADR 0008](../docs/adr/0008-options-from-free-snapshots.md))

**Goal:** serve the owner's options workflow (directional buys, verticals, iron condors) from free yfinance chains, on a separate `/options/:ticker` page. No free source keeps option IV history, so a daily snapshot starts first: every day missed is lost. One PR each, in order; each merged on the owner's go-ahead.

- [x] **PR1 — start collecting** *(#109)*: `market_calendar`, `options_math`, `options_chain`, `options_metrics` (method version 1), migration 0004, `options_snapshots`, `POST /v1/options/snapshots`, `.github/workflows/iv-snapshot.yml`, `OPTIONS_SNAPSHOT_SYMBOLS=QQQ,SPY,NVDA`. Owner: set the `API_BASE_URL` variable and the `BACKEND_SHARED_SECRET` secret on GitHub (docs/deployment.md §8). Done when a manual run writes rows, IV30 is within about 2 points of a broker's, a weekend run reports `no_new_session`, and two scheduled sessions land.
- [x] **PR2 — report API** *(#110)*: split `earnings_calendar.py` out of `earnings.py` (announcement times, before/after the open); `options_analysis` (term structure, expected-move cone, earnings event move from bracketing expiries, past earnings moves, open interest by strike, put/call ratios, claims with units); `GET /v1/options/{symbol}` (≤ 30 KB, 15-minute cache, per-symbol lock, rate limit on misses) and `GET /v1/options/{symbol}/chain/{expiry}`; IV percentile from 63 sessions, rank from 126; `options_tracked` written on a successful view.
- [x] **PR3 — the page** *(#111)* `/options/:ticker` (lazy, not in the demo): expected-move cone, term structure by days to expiry, smile, open interest by strike, implied vs past earnings moves, chain table; a link on the symbol page.
- [x] **Half-day closes** *(#112)*: `market_calendar.early_closes` (3 July, the day after Thanksgiving, Christmas Eve, each when a session) close at 1 pm; quote times, `is_close`, time to expiry and the earnings timing follow. `METHOD_VERSION` 2, so the history ranks from the first version-2 session. Raised by the AI review of #111.
- [x] **PR4 — strategy builder** *(#113)*: long call/put, verticals, iron condor; payoff, breakevens, max profit/loss, risk-neutral probability of profit at mid and at the natural price. Templates only, never ranked.
- [x] **PR5 — cited AI read** *(#114)* on the page (claims → `synth_call` → `resolve_points(max_refs=None)`), cached per symbol and quote time; no advice, forecasts or strategy suggestions; numbers checked in code; a live eval (`suite=options`).
- [x] **Edge-case review** *(branch `fix/options-edge-cases`)*: nine bugs fixed (quote time in a session's first 15 minutes, DST in time to expiry, the intraday event move, a failed schedule cached a day, a traded report still flagged, past moves on a live bar, the spot fallback after the smiles, strikes of 0, a noisy smile's probability).
- [ ] **Options follow-ups (from the review, not bugs):** the snapshot's stored `next_earnings` is the calendar's date, not `earnings_calendar.next_report_date`; fetching one more expiry costs three Yahoo calls where one would do (a chains-only `fetch_chain`); the page computes the snapshot's raw-quote detail and throws it away; `_Built.parts` is an untyped dict. Known limits of the read: a bare number in any fact's name passes as a label, the direction guard can drop a correct point that uses a synonym, a headline's numbers carry no chip, and a report rebuilt with the same quote time keeps the earlier read. A report released during a session counts as traded from that session's open (the event move and the expiry flags go by the reaction date, not the release time).
- [ ] **Owner:** compare IV30 for QQQ/SPY/NVDA with a broker after Monday's close (within about 2 points), and price two strategies in the builder against a broker's analysis tool.

## Plan — a clearer options page, and positioning views (2026-11-15)

**Goal:** the owner finds `/options/:ticker` harder to read than OptionCharts, and the gap is mostly presentation. Each OptionCharts chart has a plain title, one sentence with the key numbers, a stats table, the price marked, and expiry labels with days and weekly/monthly. It also has positioning views we lack (largest open interest, max pain, gamma and delta exposure with walls), all computable by our code from Yahoo's chains and our IVs. Rules: code computes every figure, there are no sentiment labels, the GEX/DEX assumption is stated on the page, and the AI read is unchanged for now. One PR each, in order, before tastytrade PR B:

- [x] ~~**PR 1: the official close as the spot**~~ *(#120, closed)*: Yahoo's daily history close equals its price (NVDA Nov 13: both $162.85; another vendor shows $162.92), so there is nothing to switch to.
- [ ] **PR 2: clarity pass (frontend)** *(branch `feature/options-clarity`)*: each panel's takeaway sentence, stats and ⓘ; the expiry picker's days and weekly/monthly (`expiryKind`); the price labelled on the open interest chart; the AI read showing each figure once (chips folded behind "Sources").
- [ ] **PR 3: positioning (`options_positioning.py`)** *(branch `feature/options-positioning`)*:
  - per expiry: call/put totals, the top 10 open interest contracts, max pain, GEX and DEX by strike, net GEX/DEX, the call and put walls, the gamma flip (`options_math.gamma76`/`delta76`);
  - max pain and net GEX for every expiry the report reads;
  - charts and an across-expiries table.
- [ ] **PR 4: whole-chain open interest for QQQ, SPY and NVDA** *(branch `feature/options-oi-history`)*. The owner chose this over charting the snapshot's rolling 30/90-day window, which jumps as expiries roll. It adds `option_oi_totals` (migration 0005) and a second phase of the daily run (`OPTIONS_FULL_CHAIN_SYMBOLS`, best-effort), and the page charts it once two sessions exist.
- [ ] **PR 5 (with tastytrade PR B): every expiry, live.** Open interest by expiry, max pain and GEX across the whole chain from DXLink. Owner only, never stored.

## Plan — the owner's positions and an encrypted trade copy (2026-11-15, ADR 0009 amended)

**Goal:** a page of the owner's open positions with computed analysis (what the market prices, what history shows; no advice, no prompt), and a copy of their trades both of their PCs can reach. The owner chose an encrypted copy in Neon and a key their password manager syncs.

- [ ] **PR 1 — the owner key** *(branch `feature/owner-key`)*: `require_owner` (`X-Owner-Key` on top of the shared secret, 404 unset, per-IP lockout), `GET /v1/owner/status`, CORS, the sign-in form's hidden username for password managers, deployment §10. **Owner:** make and import `OWNER_KEY`, save it in the password manager.
- [ ] **PR 2 — `GET /v1/owner/positions`** *(branch `feature/owner-positions`)*: accounts and positions from tastytrade, OCC symbols parsed, live REST quotes (mark, IV, Greeks), grouped by underlying, 15 s in memory, never stored, accounts unnumbered.
- [ ] **PR 3 — the `/positions` page** *(branch `feature/positions-page`)*: the owner unlock form and key storage, then per underlying: legs, Greeks totals, payoff at expiry and today (Black-76 in TS, held to Python), what-ifs, the risk-neutral probability of profit, how often history moved that far, earnings in the holding period, max pain and walls.
- [ ] **PR 4 — the encrypted trade copy and `/trades`** *(branch `feature/owner-trades`)*: `cryptography`, `OWNER_VAULT_KEY`, AES-256-GCM per row with the transaction id as associated data, migration 0006, sync on visit, CSV download.

## Plan — tastytrade, live and personal (2026-11-15, ADR 0009)

**Goal:** link the owner's funded tastytrade account and use it live: real-time quotes for the options page, market history (IV rank and percentile, years of daily candles), and the owner's own trades. **Within tastytrade's Open API terms:**
- their data is for trading (§8(3)), and collecting it across the market is not allowed;
- it is never shown to a third party, including an LLM provider (§8(4) and §8(6));
- figures that could stand in for theirs stay theirs (§8(10));
- it is never made public (§8(11)).

So nothing from tastytrade is stored, sent to a prompt or shown in the demo. The client only reads: it requests `scope=read` and makes GET calls only, besides the token POST. The owner's own trades are outside the terms' "Data", but stay out of the database and any prompt too. One PR each, in order.

- [ ] **PR A — connect and probe** *(code merged in #116; review follow-up on `fix/tastytrade-probe-robustness`)*: ADR 0009; `tastytrade_client` (OAuth refresh with `scope=read`, a path allowlist, backoff, an hour's pause after a refused sign-in); `dxlink` (candles, one-shot Summary/Greeks); `tastytrade_probe` (`python -m`, prints what the account gets, stores nothing). **Owner:** create the personal OAuth app and grant, set the three Fly secrets. **Done when** the probe has run on Fly during a session and its answers are recorded here: real-time or not, candle depth, whether candles carry IV, whether options have candles. **First run (2026-11-15, Sunday):** the grant is read-only (`read` and an account scope, no `trade`); the client refused it over the account scope, fixed on `fix/tastytrade-probe-robustness`; nothing else ran. **Second run (#117 deployed):**
  - Sign-in works.
  - **Chain:** SPY has 32 expiries and 258 strikes near 30 days.
  - **REST quotes** also carry open interest, IV (`volatility`), the Greeks and `theo-price`, so PR B may not need DXLink for open interest. Their mids matched Yahoo's spreads 10 of 10.
  - **Market metrics** are all filled, and NVDA has 47 past reports.
  - **The account:** 133 transactions, 2 open positions.
  - **DXLink** was refused over its host (`tasty-openapi-dxlink-md-ws.dxfeed.com`, level `api`, path `/realtime`), allowed on `fix/tastytrade-scope-strictness`.
  - **Third run (#118 deployed), and candle reads fixed on `fix/dxlink-candle-symbols`:**
    - DXLink works, with Summary (open interest) and Greeks.
    - **Daily candles:** back to 1995 (8,000 is the per-request cap), with IV on about the last 9 years.
    - **Intraday:** hourly back to February 2026; 5-minute bars about six weeks back.
    - **An option contract:** a year of daily candles with IV and open interest.
  - **Still open:** real-time quote ages, which needs a run during a session (Monday 2026-11-16).
  - **What this means for the next PRs:**
    - **B:** REST quotes already carry open interest, IV and Greeks, so live quotes need no DXLink.
    - **C:** a live chart of about 9 years of daily IV from candles, plus an option contract's price and IV path.
    - **D:** the journal can show each trade's contract path from candles.
- [ ] **PR B — live quotes on the options page:** `GET /v1/options/{symbol}/live/{expiry}`, cached 10 s; our IVs from live mids; Yahoo's open interest; a Live/Delayed switch; the builder prices at live bid/ask.
- [ ] **PR C — market history, live:** `GET /v1/options/{symbol}/history` (market metrics; daily candles, with IV if they carry it); a "History · tastytrade" panel.
- [ ] **PR D — the owner's trades:** `trade_journal` (orders to strategies, FIFO opens and closes, expirations and assignments, fees); `GET /v1/trades`; a lazy `/trades` page. Fetched on demand, account numbers masked, no advice.

## Handoff — pickup notes (2026-11-13)

If you're picking this up after a gap:

1. **Read [CLAUDE.md](../CLAUDE.md) "Current state"**, then the plan above. What shipped and why is in [docs/changelog.md](../docs/changelog.md); what the owner reacted to is in [dogfood-2026-11.md](dogfood-2026-11.md); the phase-by-phase task detail is in [archive-phases-1-5.md](archive-phases-1-5.md).
2. **Production:** dashboard <https://market-analysis-agent-red.vercel.app>, API <https://market-analysis-agent.fly.dev>, `LLM_PROVIDER=deepseek`. A push to `main` deploys both; the owner sets Fly secrets ([docs/deployment.md](../docs/deployment.md) §7). A change to report content bumps `REPORT_VERSION`, and cached reports rebuild on their next visit.
3. **Test counts and bundle sizes:** [docs/testing.md](../docs/testing.md) and [frontend/README.md](../frontend/README.md) are the only places that state them.

**Known minor issues:**

- **Vite HMR cache misses file mtime in `.claude/worktrees/...`** — see [lessons.md](lessons.md). Workaround: trust unit tests + `vite build`; fix candidate `server.watch.usePolling: true`.
- **Cancel-on-navigate** (old Bug 8): leaving a ticker page mid-generation doesn't abort the request. Hasn't bitten in dogfood.
- **Help overlay (`?` shortcut)** — still deferred; ⌘K is the only shortcut.
- **Alphabet's annual history starts in 2022.** Before then it tagged share counts per share class, which the SEC company-concept API doesn't return, so GOOGL has four years of per-share figures and multiples. The same limit applies to any company that reports shares only by class.
- **Left from the 2026-11-13 security review of the demo** (low severity; the call log, also listed, was fixed by #105): two requests arriving as a demo cache entry expires each query the database once; `tool_calls_audit` (tool names and exception class names) is public on demo reports, which was accepted.
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
- [ ] **LLM-driven section composition** (was 2.2d) — replace the static `SECTION_TO_CLAIM_KEYS` map with LLM triage. No signal yet that the deterministic catalog is too rigid.
- [ ] **Supervisor mode** (was 2.3) — multi-symbol comparative queries via specialist sub-agents. No signal that it adds factuality / structure benefit over the single-agent default.
- [ ] **Reddit / r/wallstreetbets sentiment** — narrow signal, high noise. Per ADR 0003 cut from must-have.
- [ ] **Discord bot client** — was original v1 vision; deferred indefinitely.
- [ ] **Real-time / 15-min scheduled ingest, Celery, Redis** — cut by ADR 0003.
- [ ] **Real auth + per-user cost caps + abuse logging** — only when there are real users. Phase 3.0's shared-secret gate is enough until then.

## Blocked / waiting

-
