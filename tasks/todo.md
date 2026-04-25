# TODO

Active sprint for the Market Analysis Agent.

> **Scope:** v2 per [`docs/adr/0003-pivot-equity-research.md`](../docs/adr/0003-pivot-equity-research.md). The v2 product is the **AI Equity Research Assistant**: on-demand structured reports, single agent + tools by default, free data only, citation discipline non-negotiable. Phase 1 infrastructure (FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, observability, tests, deploy pipeline) is complete and reused as-is.

## In progress

-

## Phase 2 — v2 Equity Research Assistant

### 2.0 Foundations (must land first — gate every later PR)

- [ ] **Eval harness skeleton** — `tests/evals/` with ~5 golden questions to start (P/E for AAPL on date X, latest 8-K date for NVDA, etc.) and a rubric scorer (factuality + structure + latency). Runs via `pytest tests/evals/` and on every PR.
- [ ] **Citation-enforcing structured-output schema** — define `Claim { value, source, fetched_at }` and `ResearchReport { sections: list[Section], confidence: Literal["high","medium","low"], generated_at: datetime }` Pydantic models in `app/schemas/research.py`. Every tool returns `Claim`s; the agent cannot synthesize free text outside the schema.
- [ ] **LLM client + cost-tier routing** — `app/services/llm.py` with two callables: `triage_call(...)` (small model — Haiku/equivalent, structured output, picks tools) and `synth_call(...)` (capable model — Sonnet/equivalent, structured output, writes the report). Wrapped in `log_external_call`. Add `ANTHROPIC_API_KEY` to Fly secrets + repo `.env.example`.

### 2.1 Tool registry build-out (one PR per tool)

- [ ] **`fetch_news`** — NewsAPI dev tier + 2 RSS feeds. Reuse `data_ingestion.py` provider-registry pattern. New `news_symbols` join table for symbol tagging via simple keyword match at ingest. Upsert.
- [ ] **`fetch_fundamentals`** — yfinance.info + financials/balance_sheet/cashflow → valuation (P/E, P/S, EV/EBITDA, PEG), quality (ROE, ROIC, gross-margin trend, FCF conversion), capital allocation (buybacks, dividends, SBC dilution as % of revenue), short interest. One tool, one round trip, returns a flat `dict[str, Claim]`.
- [ ] **`fetch_edgar`** — generic SEC EDGAR filing fetcher. Given `(symbol, form_type, recent_n)` returns metadata + raw text. Cache to disk between requests.
- [ ] **`parse_filing`** — purpose-built parsers built on `fetch_edgar`:
    - [ ] `form_4` — insider transactions, cluster summary
    - [ ] `13f` — institutional ownership changes (top holders + recent deltas)
    - [ ] `10k_risks_diff` — current Item 1A vs prior year, what's new
    - [ ] `10k_business` — Item 1 summary (moat / segments / customer concentration / geo mix all fall out)
- [ ] **`fetch_earnings`** — last 4 quarters: 8-K earnings releases (free, structured), transcript scrape (Motley Fool / Investor.com — fragile, gracefully fails), consensus EPS from `yfinance.Ticker.earnings_estimate`, beat/miss + magnitude.
- [ ] **`fetch_macro`** — FRED API. Sector→series map (semis: DGS10 + ISM PMI; banks: yield curve + NIM; consumer: retail sales + UMCSENT; etc.). Return one paragraph of context, cited.
- [ ] **`fetch_peers`** — hybrid: hardcoded top-N for major sectors + `yfinance.Ticker.info["sector"]` fallback. Returns 3–5 peers + a comparison matrix on 3–4 metrics.
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
