# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [`docs/adr/0003-pivot-equity-research.md`](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: on-demand structured reports, single agent + tools by default, free data only, citation discipline non-negotiable. Phase 1 infrastructure (FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, observability, tests, deploy pipeline) is complete and reused as-is.

## In progress

- Phase 3.0 — Frontend prereqs (PR A): shared-secret auth dep + CORS middleware + `GET /v1/research` list endpoint

## Phase 3 — Frontend (React + Vercel) + auth gate

> **Why React over a Streamlit MVP:** the user is React-bound either way, so the Streamlit step is pure detour (~1 day of throwaway code, no unique learnings vs raw `curl | jq` for UX discovery). Going straight to React saves the rebuild. **Why shared-password vs real auth:** ~30 min vs 1–2 days, single user (you), going semi-public. Structured as a single FastAPI dependency + a single React auth context so it can swap to Clerk/magic-link in a day when multi-user lands.

### 3.0 Backend prereqs (PR A) — must land before frontend

One PR, three commits:

- [ ] **A1 — Shared-secret auth dep** — `app/core/auth.py::require_shared_secret`. Validates `Authorization: Bearer <secret>` against `settings.BACKEND_SHARED_SECRET` via `hmac.compare_digest`. When `BACKEND_SHARED_SECRET` is unset (default), the dep is a pass-through — local dev keeps working without a token. Wire to `/v1/research/*` only (other routes can stay open until they need protecting). Tests: 401 on missing/wrong header, 200 on right header, pass-through when secret is unset.
- [ ] **A2 — CORS middleware** — `app/main.py` reads `settings.FRONTEND_ORIGIN: str | None`. When set, install `CORSMiddleware` with that origin (single origin, not `*`), allow methods `GET, POST, OPTIONS`, allow headers `Authorization, Content-Type`. Credentials disabled (we use bearer tokens, not cookies). Tests: preflight `OPTIONS` returns the right `Access-Control-Allow-*` headers when set, no CORS headers when unset.
- [ ] **A3 — `GET /v1/research`** — Paginated list of past reports for the dashboard. Returns `list[ResearchReportSummary]` (symbol, focus, report_date, generated_at, overall_confidence) — NOT the full report blob. Query params: `limit` (default 20, max 100), `offset` (default 0), `symbol` (optional filter). Backed by a new `research_cache.list_recent(session, *, limit, offset, symbol=None)`. Order by `generated_at DESC`. Auth-protected via the A1 dep. Tests: empty DB → `[]`, multiple reports ordered desc, symbol filter works, pagination works, 401 without auth header when secret is set.

Settings additions: `BACKEND_SHARED_SECRET: str = ""` (empty = auth disabled), `FRONTEND_ORIGIN: str = ""` (empty = CORS disabled). `.env.example` updated.

### 3.1 Frontend MVP (PR B)

- [ ] **`frontend/`** — Vite + React 18 + TypeScript + Tailwind + TanStack Query + Zod (mirrors `ResearchReport` schema for runtime validation).
- [ ] **Login screen** — single password field → POST a probe to `/v1/research/AAPL` with the bearer token; on 200 (or 401), persist the token to `localStorage` and route to dashboard.
- [ ] **Dashboard** — symbol input + focus dropdown (full / earnings) + refresh toggle. Submit → loading state with the "first generation takes ~30s, repeat reads <1s" copy.
- [ ] **Report renderer** — sections rendered as cards: title + confidence badge + summary prose + claims as a footnoted table (description / value / source link). 429 → "rate limit hit, retry in N seconds" banner. 503 → "synth unavailable, try again" banner.
- [ ] **Past reports list** — sidebar driven by `GET /v1/research?limit=20`. Click a row → re-fetch the full report.
- [ ] **Vercel deploy** — push-to-deploy from this repo's `frontend/` subdir. Env vars: `VITE_BACKEND_URL`, `VITE_SHARED_SECRET` (or have user paste at login screen).

### 3.2 Prod test + docs sweep (PR C)

- [ ] **Dogfood** the deployed Vercel + Fly stack against 5–10 real symbols across both focuses. Note UX rough edges, fix the high-impact ones.
- [ ] **README** — new "Frontend" section with screenshots, deploy instructions, env-var reference.
- [ ] **`design_doc.md`** — add the React + Vercel architecture row, update the data-flow diagram.
- [ ] **`CLAUDE.md`** — update "Current state" to reflect frontend, add `frontend/` to repo structure.
- [ ] **ADR 0004** — record the React-over-Streamlit and shared-password-over-real-auth decisions with the trade-offs that will trigger a revisit.

### 3.3 (Deferred) — what was the old "Phase 3" plan

The previous Phase 3 sketch (pgvector RAG / `search_history`, `compute_options`) doesn't fit what we're trying to achieve right now. To be re-scoped after the frontend ships and we have real-user feedback on what the agent's actually missing.

## Phase 2 — v2 Equity Research Assistant

### 2.0 Foundations (must land first — gate every later PR)

- [x] **Eval harness skeleton** — `tests/evals/` with rubric (structure/factuality/latency), `GoldenCase` shape, and rubric unit tests on every PR. Real-LLM golden tests live in `test_golden.py` and skip without `ANTHROPIC_API_KEY`. Cases populate as tools come online.
- [x] **Citation-enforcing structured-output schema** — `app/schemas/research.py` with `Source { tool, fetched_at, url }`, `Claim { description, value, source }`, `Section { claims, summary, confidence }`, `ResearchReport`. Every numeric fact in `summary` prose must appear in `claims` (rubric-enforced).
- [x] **LLM client + cost-tier routing** — `app/services/llm.py` with `triage_call` (Haiku 4.5) + `synth_call` (Sonnet 4.6), both forced-schema tool use, both wrapped in `log_external_call`. Prompt caching enabled on system blocks. `ANTHROPIC_API_KEY` added to `.env.example` and `app.core.settings`.
- [ ] **Set `ANTHROPIC_API_KEY` as a Fly secret** before any tool PR ships: `fly secrets set 'ANTHROPIC_API_KEY=sk-ant-...'`

### 2.1 Tool registry build-out (one PR per tool)

- [x] **`fetch_news`** (PR #13) — NewsAPI dev tier + Yahoo Finance per-ticker RSS. Provider-registry pattern matching `data_ingestion.py`. `news_symbols` join table (Alembic 0002) with composite PK + cascading FKs; symbol tagging via `app.services.symbol_tagger` (cashtag / ticker word-boundary / company-name first token, case-insensitive). Upsert via `ON CONFLICT DO UPDATE`. Provider failures isolated. `POST /v1/news/ingest` accepts optional `{"symbol": ...}`; `GET /v1/news?symbol=` filters via the join.
- [x] **`fetch_fundamentals`** (PR #14) — yfinance.info + financials/cashflow → valuation (P/E, P/S, EV/EBITDA, PEG), quality (ROE, gross/profit margin, gross-margin YoY trend), capital allocation (dividend yield, buyback yield, SBC % revenue), short interest, market cap. One tool, one round trip, flat `dict[str, Claim]`. ROIC + multi-year history + sector-relative versions deferred to follow-ups.
- [x] **`fetch_peers`** (PR #15) — curated `_TICKER_TO_SECTOR` map (~50 large-caps × 10 sectors) with `yfinance.info["industry"]` fallback. Returns sector + 3–5 peers + 4-metric comparison matrix (trailing P/E, P/S, EV/EBITDA, gross margin) per peer + per-metric medians. Per-peer `.info` failures isolated; single `log_external_call` wraps the whole fan-out.
- [x] **`fetch_edgar`** (PR #17) — generic SEC EDGAR filing fetcher. Given `(symbol, form_type, recent_n)` returns metadata + raw text. Disk-cached between requests, accession-indexed. Polite-crawl: SEC `User-Agent` + ≤10 req/sec (provider sleeps 0.15s between calls). 13F-HR added in PR #22 with `cik=` bypass for institution filings.
- [x] **`parse_filing`** — purpose-built parsers built on `fetch_edgar`:
    - [x] `form_4` (PR #19) — insider transactions, cluster summary (10 Claims: net P/S, top buyer/seller, cluster window, etc.)
    - [x] `13f` (PR #22) — institutional ownership changes via curated 19-asset-manager whitelist + CUSIP filtering; aggregator returns 8 Claims (top holders, position deltas, share count).
    - [x] `10k_risks_diff` — current Item 1A vs prior year. Mechanical paragraph-level diff with fuzzy match (default 0.6 similarity) so cosmetic edits don't get flagged as new risks; agent reads only the small `added_paragraphs` list to compose "what's new in risks" with high-confidence citations.
    - [x] `10k_business` (PR #21) — Item 1 (Business) and Item 1A (Risk Factors) regex extraction over BS4-flattened text with longest-match heuristic; returns `Extracted10KSection` for the agent to summarize at synth time.
- [x] **`fetch_earnings`** (PR #18) — last 4Q EPS history + forward consensus from `yfinance.Ticker.earnings_dates` / `.earnings_estimate`; beat-rate + magnitude. 21 Claims.
- [x] **`fetch_macro`** (PR #20) — FRED API with sector→series map (semis: DGS10 + ISM PMI; banks: yield curve + NIM; consumer: retail sales + UMCSENT; etc.). Sector resolution extracted into `app/services/sectors.py`.
- [ ] **`search_history`** — pgvector RAG over our stored news + filings. Time-weighted (`semantic × exp(-λ × hours_since)`). Adds the `vector` extension to Neon and an `embeddings` column to relevant tables via Alembic.
- [ ] **`compute_options`** — yfinance `option_chain` for nearest expiry → IV percentile (snapshot daily, build the history ourselves), term structure, implied move from at-the-money straddle. Daily snapshot job needed; Alembic migration for `option_iv_history` table.

### 2.2 Agent + endpoint

- [x] **`POST /v1/research/{symbol}`** (PR #26) — deterministic-everything-except-prose architecture. Static `Focus → sections → tools → claim builders` registry; orchestrator runs tools in parallel, isolates failures, calls Sonnet for prose-only with forced `SectionSummaries` schema; confidence stamped programmatically. 7 sections (`full`) or 3 sections (`earnings`). Real-LLM golden eval at factuality 0.97. **LLM-driven section composition deferred to 2.2d** if eval shows the static catalog is too rigid.
- [x] **Same-day response cache** (PR #28) — `research_reports` table (Alembic 0003) keyed on `(symbol, focus, report_date)` in `settings.TZ`. JSONB stores serialized `ResearchReport`; lookup is time-windowed via `generated_at` so the 168-hour default is configurable per env without schema change. `?refresh=true` overwrites the same-day row. Failed orchestrations not cached.
- [x] **Rate limit** on `/v1/research/*` (PRs #29 + this PR) — in-memory per-IP token bucket, default 3/hour (`RESEARCH_RATE_LIMIT_PER_HOUR`). X-Forwarded-For aware. **Runs *after* the cache lookup**, so cache hits are free; only synthesis-bound requests (cache miss or `?refresh=true`) consume tokens. Returns 429 + `Retry-After` on deny. See README §"Rate limit posture" for the trade-off.

### 2.2d Optional — LLM-driven section composition (only if eval needs it)

- [ ] **LLM triage replaces the static SECTION_TO_CLAIM_KEYS map.** Phase 2.2d kicks in if the rubric shows the deterministic catalog is too rigid (e.g. consistently misses sector-specific framings the LLM would produce). Currently no signal that this is needed.

### 2.3 Optional — supervisor mode (only if a real query needs it)

- [ ] **Specialist sub-agents** — Research, Technical, Sentiment, Earnings. Activated by a `?supervisor=true` flag for multi-symbol or comparative queries.
- [ ] **ADR 0004** documenting when supervisor mode adds value vs single agent. Cut it if the eval harness shows no factuality / structure benefit.

## Cross-cutting (do alongside, not blocked on Phase 2)

- [ ] Turn on branch protection for `main` and add `ANTHROPIC_API_KEY` as a repo secret for the AI PR review job
- [ ] `.python-version` already pinned; verify it's respected by CI's uv setup

## Future scope (revisit later, deliberately not Phase 2)

- [ ] **Reddit / r/wallstreetbets sentiment** — real signal is narrow (high-retail-attention names only), noise is high. Revisit if a specific recurring eval query genuinely benefits from it. ADR 0003 cuts this from must-have.
- [ ] Discord bot client — was original v1 vision; deferred indefinitely.
- [ ] Real-time / 15-min scheduled ingest, Celery, Redis — cut by ADR 0003.
- [ ] Auth + per-user cost caps + abuse logging — only when we have real users.
- [ ] Web frontend — small dashboard for browsing past reports + triggering new ones.

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

## Blocked / waiting

-
