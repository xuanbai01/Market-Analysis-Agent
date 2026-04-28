# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [`docs/adr/0003-pivot-equity-research.md`](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: on-demand structured reports, single agent + tools by default, free data only, citation discipline non-negotiable. Phase 1 infrastructure (FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, observability, tests, deploy pipeline) is complete and reused as-is.

## In progress

-

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

- [ ] **`POST /v1/research/{symbol}`** — single-agent default mode. Takes `focus` (`earnings | technical | full`) + `include_sentiment`. The triage call picks tools; synth call composes the report. Strict structured output. Per-section `confidence`. Audit trail of tool calls captured.
- [ ] **Per-symbol response cache** — same-day requests return cached unless `?refresh=true`. Cache in `research_reports` table keyed on `(symbol, focus, date)`.
- [ ] **Rate limit middleware** on `/v1/research/*` — N reports / hour / IP. Slowapi or hand-rolled.

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
