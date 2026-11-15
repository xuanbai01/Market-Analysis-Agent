# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

> **Product context:** this repo is the **AI Equity Research Assistant** — a FastAPI backend exposing `POST /v1/research/{symbol}` that returns a Pydantic-typed citation-backed research payload, plus a React + Vite frontend rendering it as a **symbol-centric dashboard at `/symbol/:ticker`** (Phases 1–5 done; deployed at https://market-analysis-agent-red.vercel.app → https://market-analysis-agent.fly.dev). Single agent + well-designed tools, free data only, citation discipline non-negotiable. **Visual-first, delta-driven** product shape (charts > prose), with **adaptive layouts** for distressed names. The original v1 vision (real-time multi-agent platform, Discord bot) was cut by [ADR 0003](docs/adr/0003-pivot-equity-research.md); the visual-first commitment (no Morningstar-narrative chase) is in [ADR 0004](docs/adr/0004-visual-first-product-shape.md); the pivot from generated-report-page to symbol-centric-dashboard is in [ADR 0005](docs/adr/0005-symbol-centric-dashboard.md).
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

Phases 1–5 are shipped and deployed. The open plan is in [`tasks/todo.md`](tasks/todo.md). What shipped, PR by PR, is in [`docs/changelog.md`](docs/changelog.md) — read the entry for a feature before changing it.

**What exists**

- **Backend:** `POST /v1/research/{symbol}` builds a report. Tools fan out in parallel (`fetch_fundamentals`, `fetch_earnings`, `fetch_peers`, `fetch_macro`, `fetch_news`, `fetch_business_info`, the 10-K extractors, `fetch_annual_history`, `fetch_insider_activity`); code builds the claims and the derived comparisons (`research_derived.py`); two LLM calls in parallel write the section prose and the analyst view (`research_thesis.py`); code checks citations and sets confidence and layout signals. Also `GET /v1/market/{symbol}/prices`, `GET /v1/market/overview`, `GET /v1/lens/{id}`, `GET /v1/options/{symbol}` (the options page's data), `GET /v1/options/{symbol}/read` (its cited AI read) and `POST /v1/options/snapshots`, which a GitHub Actions cron calls after each US close to record option IVs (ADR 0008). A read-only client for the owner's tastytrade account (`tastytrade_client`, `dxlink`; ADR 0009) serves `python -m app.services.tastytrade_probe` and `GET /v1/owner/positions` (the owner's positions with live quotes, behind the owner key).
- **Frontend:** the `/trades` page (the owner's transactions from the encrypted copy, with a CSV) and the `/positions` page (the owner's tastytrade positions, behind the owner key: legs at live marks, Greeks in dollars, payoff and what-ifs, the chance of profit option prices imply, how often history moved that far; ADR 0009), the `/options/:ticker` page (ADR 0008; with a strategy builder and a cited read; linked from the dashboard, not in the demo), the `/symbol/:ticker` dashboard (one card per section, reordered for distressed names), `/compare`, `/lens/:id`, search / watchlist / recent, the market strip, and a public read-only demo at `/demo` (`useDemo()` switches the fetchers and hides what a visitor can't do). Charts are hand-rolled SVG; there is no charting library.
- **Production:** Vercel + Fly + Neon behind the shared secret, `LLM_PROVIDER=deepseek` ([ADR 0006](docs/adr/0006-pluggable-llm-provider.md); the code default is `anthropic`). `FRED_API_KEY` is set there (since 2026-11-13), so the Macro card renders; `NEWSAPI_KEY` is not, so news comes from Yahoo's feed only. The `TASTYTRADE_*` secrets are not set yet (docs/deployment.md §9).

**Tables today:** `symbols`, `news_items`, `news_symbols`, `candles`, `research_reports`, `option_iv_snapshots`, `options_tracked`, `option_oi_totals`, `owner_transactions` (the owner's trades, encrypted per row). pgvector + `embeddings` columns are not added until/unless `search_history` un-defers.

**Rules that came out of shipped work** (the changelog or `tasks/lessons.md` has the story behind each):

- **Bump `REPORT_VERSION`** (`app/services/report_version.py`, now 8) in the same PR as any change to what a fresh report contains; cached reports then rebuild on their next visit (docs/conventions.md).
- **Code computes, the model writes** ([ADR 0007](docs/adr/0007-analytical-narratives.md)). A comparison the prose should make is a derived claim in `research_derived.py`; the prompt forbids arithmetic and the factuality rubric fails any number no claim holds.
- **Run the live golden eval before merging a change to report content** (prompts, claims, tools, the thesis): `uv run pytest -m live_llm tests/evals -s`, or the Live Eval workflow on GitHub.
- **A claim that renders carries a `unit`.** The frontend formats from the unit, never from the size of the number.
- **News headlines are not analyst-view inputs** — a live run turned a headline into a bear point with unrelated evidence.
- **A tool that found nothing is `empty`, not `ok`** in `tool_calls_audit`, and the dashboard names it ("Not in this report"). A tool with always-present metadata needs its own check in `research_orchestrator._found_nothing` (see `fetch_macro`).
- **A company that moved to a new SEC registrant gets a line in `app/services/sec_registrants.py`**, checked against SEC. SEC publishes no link between the two, and the 10-Ks and XBRL history stay under the old one.
- **Peers carry only Yahoo's figures, so a peer comparison uses the subject's Yahoo figure too** (`gross_margin_ttm`), not one computed from statements.
- **A fiscal-year figure is not today's.** The year-end multiples (`valuation_history.py`) are as of each fiscal year's last trading day; today's are the trailing claims. Descriptions say which, and both prompts tell the model to name the year.
- **CPU-heavy work runs off the event loop, and a 10-K is parsed once.** `ten_k._flat_filing` parses each filing once with lxml for both 10-K tools, and it and the risk paragraph diff run on the 10-K tools' own thread (`_TEN_K_EXECUTOR`), one piece at a time. The parse streams, collapsing each element into its text as it ends, so only open elements and one string per finished child are in memory. A big filer's report (JPM) blocked every request for seconds and was killed at 512 MB; measure memory on Linux, not Windows (`tasks/lessons.md`).
- **A CPU-second costs sixteen on Fly.** The shared CPU runs at 1/16 of a core once its burst balance (5 s at boot) is spent, so a build's wall time there is about 16× its CPU time. RIVN's risk diff (20 CPU-seconds) made its builds take 4–5.5 minutes; it now bounds `difflib.ratio()` by the LCS (`rapidfuzz`) and takes 0.7. Measure CPU work under the quota: `systemd-run --user --scope -p CPUQuota=6.25% -p CPUQuotaPeriodSec=80ms` in WSL. `fly logs` shows each external call's latency (`app/core/logging.py`).
- **A request holds no database connection while a report builds.** `POST /v1/research` ends the cache lookup's transaction before the build and saves on a fresh connection; a save that loses its connection serves the report uncached. A 5.5-minute RIVN build lost its report when Neon dropped the idle connection.
- **Every SEC request goes through `edgar._sec_get`**, which spaces all of them in the process (several tools hit SEC from parallel threads; SEC allows 10 a second).
- **SEC's list of a company's filings is paged.** `filings.recent` holds one year for a big filer (JPM: 26,000 filings); `edgar._recent_filings` reads the older pages for the rest, back three years. Check a change to it against a bank, not just AAPL.
- **Insider trades are officers' and directors' purchases and sales** of the company's own stock (`form_4.py`): 10% holders apart, other issuers' Form 4s out, grants and withholding counted as routine.
- **A section needs a card.** `CARD_SECTIONS` in `SymbolDetailPage.tsx` lists the sections with one; any other section falls to the plain `ReportRenderer` table until its card exists.
- **A card with nothing to draw returns null**, and a row counts only the cards that will render (each card's own empty check), so no row reserves an empty column.
- **Every `lazy()` goes through `lib/lazy-with-reload.ts`**, and every authenticated route except `/` is its own chunk. The main chunk must stay under 100 KB gzipped (current sizes: `frontend/README.md`).
- **Option figures are ours, from the quote time.** Every IV is Black-76 on a put-call-parity forward from bid/ask, never Yahoo's column; time to expiry runs from the quote time (the last close outside a session, `market_calendar.quote_time`), not the clock, to the expiry's close (1 pm on NYSE's half days, `early_closes`). A snapshot row is never updated; a method change bumps `options_metrics.METHOD_VERSION` and is recomputed from the stored quotes (ADR 0008).
- **Positioning figures assume who holds what, and say so.** `options_positioning` computes max pain, gamma and delta exposure (dollars per 1% move: GEX = Γ·F²·OI, DEX = Δ·F·OI on the forward), the walls and the gamma flip from Yahoo's open interest and our own IVs, gamma exposure under the common convention that dealers are long the calls and short the puts, delta exposure as the options' own delta (calls +, puts −, no assumption). The page states this beside the numbers. Open interest figures match OptionCharts to the contract (NVDA, 2026-11-16 expiry). Some sites' "delta exposure per 1%" is total dollar delta, 100 times ours.
- **An AI read that quotes numbers is checked in code, not only by the rubric.** The options read (`options_read.py`) drops any point quoting a figure none of its cited claims shows (`research_thesis.unbacked_numbers`; a number with a unit is a figure, not a label) or turning a cited comparison round, and a headline with an unbacked number spoils the read. A comparison it makes must be one a claim states, with the direction in the claim's words.
- **The next report date has one rule,** `earnings_calendar.next_report_date` (the calendar's date unless it's on or before the latest report, else the next scheduled row), shared by the Earnings section and the options page. An implied earnings move is refused, with the reason, rather than read off a straddle that mostly prices other days.
- **Every route takes `require_shared_secret`** except `/`, `/v1/health` and the demo; `tests/test_route_auth.py` fails on any other ungated route. The only open data routes are the three under `/v1/demo`: stored data for `DEMO_SYMBOLS`, never a generated report or a provider call (`app/services/demo.py`). Don't add a fourth, or anything that can spend, without a decision. **The owner's account routes (`/v1/owner`) also take `require_owner`**: `X-Owner-Key` on top of the shared secret, 404 with `OWNER_KEY` unset, a per-IP lockout after wrong keys; `tests/test_owner_auth.py` pins them (ADR 0009, amended).
- **A new runtime dependency goes in the Dockerfile too** — it has its own pin list; `tests/test_dockerfile_deps.py` fails on drift.
- **tastytrade's data is live and the owner's alone** ([ADR 0009](docs/adr/0009-tastytrade-live-personal.md); its Open API terms §8). Never store it, put it in a prompt or show it in the demo. A Claude session is a third party too: checks print metadata (ages, counts, yes/no), never tastytrade's values. The client asks for `scope=read`, uses a token only when its scope is known and read-only, GETs only allowlisted paths, and remembers every failed sign-in (repeated failures block the IP); DXLink connects only to tastytrade's feed host and follows no redirect. The owner's own trades are theirs, but stay out of prompts.
- **The owner's trades are stored encrypted, and nothing else of theirs is** (ADR 0009, amended). `owner_vault` seals each transaction (AES-256-GCM, `OWNER_VAULT_KEY`, the id as associated data); only the id and an estimated-fee flag are in the clear, and no account number is stored. Positions and tastytrade's market data are never stored. The positions page reads option reports with `track=false`, so holdings aren't recorded as views. A Claude session checks counts only, never decrypting a trade.
- **Never fetch CNN's fear & greed endpoint by disguising the client.** The strip shows our own estimate, labelled "est." (`app/services/market_sentiment.py`).

**Deferred**

- **Phase 6 (XBRL Tier 2):** segment + geography revenue breakdowns, RPO. The 4.8 dogfood didn't ask for them; segment data needs a filing-level XBRL parser beyond `app/services/xbrl.py`.
- **Indefinitely, per ADR 0004:** `search_history` (pgvector RAG), Reddit sentiment, real auth + per-user cost caps.
- **Logo URL resolution** — HeroCard renders a letter placeholder.

When making changes, prefer extending the existing shape (new claims, new history fields, new sections in the static `SECTIONS_BY_FOCUS` registry) over adding parallel surfaces. The deterministic-everything-except-prose architecture is the discipline — read [`app/services/research_orchestrator.py`](app/services/research_orchestrator.py) before proposing structural changes.
