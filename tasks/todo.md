# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [ADR 0003](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: on-demand structured reports, single agent + tools by default, free data only, citation discipline non-negotiable. Phase 1 infrastructure (FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, observability, tests, deploy pipeline) is complete and reused as-is.
>
> **Product shape:** [ADR 0004](../docs/adr/0004-visual-first-product-shape.md) — visual-first, delta-driven. Multi-year history rendered as charts; LLM commentary stays short and stays at genuinely judgment-dependent moments. **Not** chasing Morningstar-depth analyst narrative.

## In progress

- Phase 3 — Visual-first depth (just kicking off)

## Phase 3 — Visual-first depth (active)

> **Why this is Phase 3:** dogfooding the v1 report against several names surfaced a clear gap — point-in-time numbers without historical context feel shallow even when the underlying data is comprehensive. The fix isn't more LLM prose (per ADR 0003 anti-hallucination disciplines, prose stays short and citation-bound); the fix is multi-year history surfaced as charts. See [ADR 0004](../docs/adr/0004-visual-first-product-shape.md).
>
> **What this is NOT:** a chase of Morningstar-depth analyst narrative. No multi-year DCF projections, no fair-value estimates, no 5-page bull/bear essays. Those land (in attenuated form) in Phase 4, after the data foundation is right.
>
> **Frontend deploy status:** held until Phase 3 ships. PR #32 (frontend MVP) is merged on `main` and locally tested but not Vercel-deployed. The frontend will pick up history rendering as part of this phase rather than ship a deploy that immediately needs an upgrade.

### 3.1 Schema — `Claim.history`

- [ ] **`ClaimHistoryPoint`** — Pydantic model: `{period: str, value: float}`. `period` is a string (e.g. `"2024-Q4"`, `"2024-12"`, `"2024"`) — different tools emit different granularities; the rendering layer reads them as opaque labels. `value` is a number (no `ClaimValue` union — only numeric points are charted).
- [ ] **`Claim.history: list[ClaimHistoryPoint] = Field(default_factory=list)`** — added to `app/schemas/research.py`. Default empty so existing claims and existing cache rows round-trip unchanged. Ordered oldest-to-newest by convention; the renderer doesn't sort.
- [ ] **Mirror in `frontend/src/lib/schemas.ts`** — Zod schema gets the same optional field; existing reports parse unchanged.
- [ ] **Round-trip test** — write a `Claim` with history → JSONB → read back → unchanged. Empty history round-trips as empty.

### 3.2 Tool extensions (one PR per tool, one commit per tool's history field)

The pattern: each builder learns to populate `Claim.history` for the metrics where yfinance / FRED / derived computation gives us a series. Builders that can't (e.g. peer-comparison single-snapshot metrics) leave history empty.

- [ ] **`fetch_fundamentals` history** — yfinance `Ticker.quarterly_financials`, `quarterly_balance_sheet`, `quarterly_cashflow` give ~5 years of quarters. Add history for: revenue, net income, gross margin, operating margin, EPS, ROE. Wrap the new yfinance call in `log_external_call`. Defensive about NaN / missing quarters (skip the point, don't fail the tool).
- [ ] **`fetch_earnings` history** — already pulls earnings dates; extend lookback from 4 quarters to ~20. Beat / miss flags become a binary time series. Forward-consensus EPS gets a history field reflecting analyst-revision drift if `Ticker.earnings_estimate` exposes it cheaply; cut otherwise.
- [ ] **`fetch_macro` history** — FRED already returns series-level data. Surface the last ~24–60 months on each macro claim's history (sector-dependent — short rates need higher cadence than ISM PMI).
- [ ] **`fetch_valuation_history` (new derived tool)** — combines `fetch_fundamentals` history + price history into rolling P/E, P/S, EV/EBITDA over time. Gives "AAPL trades at 28x today vs a 5-year median of 26x." Pure compute; no new external call. Decide whether this is its own tool or inlines into `fetch_fundamentals`'s builder.
- [ ] **Price-and-technicals history** — we already have OHLCV in `candles`; surface ~5y closing prices on a price-history claim, plus rolling SMA/RSI as charts. Reuse `app.services.technicals` rather than adding a new tool.
- [ ] **Peers** stay as point-in-time scatter (peer-comp gets a *visualization* upgrade in 3.3 but not a history field — comparing 5y trends across 5 peers is a different chart shape, defer).

### 3.3 Frontend visualization

- [ ] **`Sparkline` component** — Recharts `LineChart` configured for inline density (~80×24 px). No axes, no legend, no tooltip on the inline variant. Renders any `Claim.history` of length ≥ 2.
- [ ] **`ClaimRow` integration** — in `ReportRenderer`, the "Value" cell renders `formatClaimValue(value) | <Sparkline history={claim.history} />` when history is present. Mobile width drops the sparkline gracefully.
- [ ] **`SectionChart` component** — bigger chart for sections that warrant a top-level visualization (price + SMA overlay; fundamentals trend; macro series). One `SectionChart` per section max. Picks the right "headline" claim per section by builder convention (e.g. Valuation → Trailing P/E, Quality → Gross Margin, Earnings → EPS).
- [ ] **`PeerScatter` component** — for the Peers section, render the peer-comparison matrix as a 2-D scatter (e.g. P/E on x, gross margin on y). Color-code the subject vs peers. Single chart replaces the table for the Peers section (or augments it — a11y consideration: keep the table for screen readers).
- [ ] **Recharts dependency** — `npm install recharts`. Tree-shaken bundle adds ~30 KB gzipped. Verify build still under 100 KB gz.

### 3.4 Eval rubric extension

- [ ] **`_matches_claim` reads history** — when checking a number from prose against claim values, also check `claim.history[*].value`. A summary that says "EPS rose from 1.46 to 2.18" passes if both numbers appear anywhere in the referenced claim's history.
- [ ] **New golden case** with a history-bearing claim — verifies the rubric extension is exercised in CI, not just unit-tested.

### 3.5 Frontend deploy (after 3.1–3.4 land)

- [ ] **Vercel deploy** — push-to-deploy from `frontend/`. Set `VITE_BACKEND_URL`, set backend `FRONTEND_ORIGIN`, set `BACKEND_SHARED_SECRET` on both sides. README's "Deploying to Vercel" section already covers this.
- [ ] **Dogfood** the deployed stack against 5–10 real symbols. Note UX rough edges; fix the high-impact ones in a follow-up.
- [ ] **README + design_doc + CLAUDE.md** sweep — current state reflects Phase 3, screenshots, deploy URL.

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

## Blocked / waiting

-
