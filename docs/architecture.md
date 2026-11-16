# Architecture

Read this before opening source files. The [design_doc.md](../design_doc.md) at the repo root is the long-form system design; this page is the short version of what actually exists in code today and where it's heading.

## Project Overview

The **AI Equity Research Assistant** — a FastAPI backend that exposes one primary endpoint (`POST /v1/research/{symbol}`) returning a Pydantic-typed citation-backed structured research report, plus a React + Vite + TypeScript frontend that renders it. Single agent + well-designed tools, free data only, citation discipline non-negotiable. Visual-first, delta-driven product shape per [ADR 0004](adr/0004-visual-first-product-shape.md).

The original v1 vision (real-time multi-agent platform with scheduled news firehose, Discord bot, Pinecone vector store, Polygon paid feed) was [explicitly cut](adr/0003-pivot-equity-research.md) in favour of depth-over-freshness on free data.

Real operating cost: ~$0–5/mo (Fly auto-stop + Neon free tier + per-call LLM billing under cost-tier routing; under a cent per fresh report on DeepSeek Flash).

## Tech Stack

| Layer | Technology | Status |
|---|---|---|
| Language | Python 3.11 (backend), TypeScript 5.6 (frontend) | ✅ |
| Backend framework | FastAPI 0.115 | ✅ |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | ✅ |
| Config | pydantic-settings | ✅ |
| Database | PostgreSQL 15 (Docker locally; Neon free tier in prod) | ✅ |
| Schema migrations | Alembic 1.13 (async mode) | ✅ |
| LLM | Switchable via `LLM_PROVIDER` ([ADR 0006](adr/0006-pluggable-llm-provider.md)): Anthropic — Claude Haiku 4.5 (triage: risk + news categorizers) + Sonnet 4.6 (synth), the default; or DeepSeek V4.1 Flash (`deepseek-flash`) for both tiers. Per-tier override via `LLM_TRIAGE_MODEL` / `LLM_SYNTH_MODEL` | ✅ |
| Market data | yfinance | ✅ |
| News | NewsAPI free tier + Yahoo per-ticker RSS | ✅ |
| Filings | SEC EDGAR (with disk cache + polite-crawl) | ✅ |
| Macro | FRED API | ✅ |
| Broker data | tastytrade Open API, the owner's own account: read-only, live only, never stored or sent to an LLM ([ADR 0009](adr/0009-tastytrade-live-personal.md)) | PR A: client, DXLink, probe |
| Hosting | Fly.io (auto-stop machines) + Neon (Postgres) + Vercel (frontend) | ✅ API https://market-analysis-agent.fly.dev, dashboard https://market-analysis-agent-red.vercel.app |
| Frontend stack | Vite + React 18 + Tailwind + TanStack Query + Zod | ✅ |
| Tests | pytest + pytest-asyncio (backend), vitest + happy-dom (frontend) | ✅ counts in [testing.md](testing.md) |
| Lint | ruff (backend), ESLint (frontend) | ✅ |
| CI | GitHub Actions (tests + Gitleaks + DeepSeek PR review) + push-to-deploy, and one daily cron (IV snapshot) | ✅ |

**Indefinitely deferred per [ADR 0004](adr/0004-visual-first-product-shape.md):** pgvector (`search_history`), Redis (no horizontal-scale rate limit need yet), Celery (the one scheduled job, the daily IV snapshot, is a GitHub Actions cron calling the API; ADR 0008).

## Repository Structure

```
/
├── app/                         # FastAPI application
│   ├── main.py                  # App factory, router mounting, CORS, error handlers
│   ├── core/                    # settings, auth, cors, errors, observability
│   ├── api/v1/
│   │   ├── dependencies.py      # DB session, rate limit
│   │   └── routers/             # health, symbols, news, market, research (the v2 surface)
│   ├── db/
│   │   ├── session.py           # async engine + sessionmaker
│   │   └── models/              # Symbol, NewsItemModel, NewsSymbol, Candle, ResearchReportRow
│   ├── schemas/                 # Pydantic request/response (research.py is the v2 schema)
│   └── services/                # tools (fetch_*, parse_*), orchestrator, cache, rate_limit, llm
├── alembic/versions/            # 0001 baseline, 0002 news_symbols, 0003 research_reports, 0004 option snapshots, 0005 option OI totals, 0006 owner transactions
├── frontend/                    # Vite + React 18 + TS dashboard (Phase 4)
│   ├── src/
│   │   ├── App.tsx              # Router + auth guard. SymbolDetailPage + ComparePage lazy.
│   │   ├── components/
│   │   │   ├── AppShell.tsx     # Sidebar + main outlet + global ⌘K listener
│   │   │   ├── SidebarShell.tsx # Search/Home/Compare + live Watchlist & Recent; collapses to a 64px rail
│   │   │   ├── MarketStrip.tsx  # markets row above every page + fear & greed (est.) breakdown
│   │   │   ├── LandingPage.tsx  # / route — search + past reports
│   │   │   ├── SymbolDetailPage.tsx  # /symbol/:ticker (LAZY chunk)
│   │   │   ├── compare/         # /compare/?a&b sub-tree (LAZY chunk)
│   │   │   ├── lens/            # /lens, /lens/:id (LAZY chunks)
│   │   │   ├── search/          # SearchModal (LAZY chunk)
│   │   │   └── ...              # Strata cards: HeroCard, AnalystViewCard, QualityCard,
│   │   │                        #   EarningsCard, ValuationCard, PerShareGrowthCard,
│   │   │                        #   CashAndCapitalCard, CapitalReturnsCard, RiskDiffCard,
│   │   │                        #   MacroPanel, BusinessCard, NewsList, ContextBand,
│   │   │                        #   SectionNav, ReportFreshness, ErrorBoundary,
│   │   │                        #   HeaderPills, NarrativeStrip, WatchlistButton + SVG primitives
│   │   └── lib/                 # Zod schemas, API client, auth helpers, format helpers,
│   │                            #   per-card extractors, watchlist + recent localStorage,
│   │                            #   popular-tickers
│   └── vercel.json              # Vercel deploy config (SPA rewrites; builds on push to main)
├── tests/                       # pytest-asyncio; per-test SAVEPOINT rollback. Plus tests/evals/ (rubric + golden)
├── docs/                        # this directory (architecture, security, testing, commands, ADRs)
├── tasks/                       # active sprint (todo.md) + lessons learned
├── scripts/                     # smoke.py — exercises each tool against live providers
├── design_doc.md                # long-form system design (read first)
├── fly.toml
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Layering Rule

Route handler → Service (or repository) → Model/DB. Never put business logic in a route. Never return an ORM object directly from a route; pass through a Pydantic response schema.

```
FastAPI router  ─▶  services/<domain>_<role>.py
                         │
                         ▶  db/models/<domain>.py  (SQLAlchemy)
                         ▶  external providers (yfinance, EDGAR, FRED, Anthropic / DeepSeek)
```

For the v2 research endpoint specifically:

```
POST /v1/research/{symbol}
  └▶ research_cache.lookup_recent       (free; pre-rate-limit; a report older than
                                          REPORT_VERSION is rebuilt, or served if the rebuild can't run)
  └▶ enforce_research_rate_limit         (only on cache miss)
  └▶ research_orchestrator.compose_research_report
       ├▶ tool fan-out (asyncio.gather, return_exceptions=True)
       │    fetch_fundamentals / fetch_earnings / fetch_peers /
       │    fetch_macro / extract_10k_business / extract_10k_risks_diff /
       │    fetch_annual_history (SEC XBRL, ten years per share + year-end multiples) /
       │    fetch_insider_activity (Form 4s, last six months)
       ├▶ deterministic claim builders   (per-section, code picks claims, not LLM)
       ├▶ llm.synth_call                 (Sonnet writes summary prose under forced schema)
       ├▶ research_thesis.compose_thesis (in parallel: the analyst view, claim-id citations)
       └▶ research_confidence.score_section  (programmatic, not LLM-set)
  └▶ research_cache.upsert
```

## Data Model (current)

| Entity | Fields | Notes |
|---|---|---|
| `symbols` | `symbol` (PK, varchar 16), `name` (varchar 128, nullable) | Seeded with NVDA, SPY. |
| `news_items` | `id` (PK, varchar 64), `ts` (timestamptz), `title`, `url`, `source` | Indexed on `ts DESC`. |
| `news_symbols` | composite PK `(news_id, symbol)` | Join table for symbol-tagged news. Cascading FKs both directions. |
| `candles` | composite PK `(symbol, ts, interval)`; OHLCV + volume | FK → `symbols`. Indexed `(symbol, interval, ts DESC)`. Append-only. |
| `option_iv_snapshots` | composite PK `(symbol, trade_date)`; IV30/IV90 (+ extrapolated flags), `skew25`, `rv20`/`rv60`, call/put open interest and volume, `next_earnings`, `method_version`, `detail` (JSONB: each expiry's forward, smile and raw near-money quotes) | Daily IV history (ADR 0008). Insert-only, first good row wins; ~7 KB a row. |
| `options_tracked` | `symbol` PK, `last_viewed` (timestamptz) | Symbols whose options page was opened; snapshotted for 60 days. |
| `option_oi_totals` | composite PK `(symbol, trade_date)`; call/put open interest and volume over every listed expiry, `expiries` read of `listed` | Whole-chain totals for `OPTIONS_FULL_CHAIN_SYMBOLS` (QQQ, SPY, NVDA), written by the daily run after its snapshots, insert-only. The snapshot's own open interest covers only its 30/90-day window. |
| `owner_transactions` | `id` PK (tastytrade's transaction id), `key_version`, `nonce` (12 bytes, checked), `ciphertext`, `estimated_fee` | The owner's trade copy (ADR 0009, amended): each transaction sealed with AES-256-GCM under `OWNER_VAULT_KEY`, the id, key version and flag bound to it as associated data; nothing else in the clear. Written once; a row stored with estimated fees is replaced once they're final. |
| `research_reports` | composite PK `(symbol, focus, report_date)`; `report_json` (JSONB), `generated_at` (timestamptz) | Same-day cache. JSONB stores serialized `ResearchReport`. Lookup is time-windowed via `generated_at` (configurable via `RESEARCH_CACHE_MAX_AGE_HOURS`). |

## Backend routes (current)

| Group | Routes | Status |
|---|---|---|
| Health | `GET /v1/health` | ✅ real (pings DB) |
| Symbols | `GET /v1/symbols`, `POST /v1/symbols` | ✅ real. Auth-gated. |
| News | `POST /v1/news/ingest`, `GET /v1/news`, `GET /v1/news/{id}` | ✅ real (NewsAPI + Yahoo RSS, symbol-tagged). Auth-gated (`POST` spends NewsAPI quota; the reads show which tickers are tracked). |
| Market | `POST /v1/market/ingest`, `GET /v1/market/{symbol}`, `GET /v1/market/{symbol}/history` | ✅ real (yfinance ingest + upsert + technicals). Auth-gated. |
| **Research** | **`POST /v1/research/{symbol}?focus={full,earnings}&refresh={false,true}`** | ✅ **the v2 primary endpoint.** Auth-gated when `BACKEND_SHARED_SECRET` is set. Per-IP rate limit. |
| Research list | `GET /v1/research?limit=20&offset=0&symbol=...` | ✅ paginated `ResearchReportSummary[]` for the dashboard sidebar |
| Phase 4 — prices | `GET /v1/market/:ticker/prices?range={60D\|1Y\|5Y}` | ✅ Phase 4.1 — read-through `candles` cache, falls through to yfinance ingest on miss. Auth-gated. |
| Market strip | `GET /v1/market/overview` | ✅ 2026-11 — headline quotes (S&P 500, Nasdaq 100, Dow, VIX, Russell 2000, US 10Y, dollar, gold, WTI, bitcoin) + our fear & greed estimate (`market_sentiment.py`: momentum, VIX, safe-haven and junk-bond demand, each ranked against its past year). yfinance, in-memory cache (5 min quotes / 1 h sentiment), serves stale on provider failure. Auth-gated. |
| Demo | `GET /v1/demo`, `GET /v1/demo/research/{symbol}`, `GET /v1/demo/market/{symbol}/prices` | ✅ 2026-11 — public and read-only: the latest stored report and stored prices for the tickers in `DEMO_SYMBOLS`. Never generates or fetches; responses cached 5 min as bytes; per-IP limit. **Not auth-gated, by design** (security.md A01). |
| Options | `POST /v1/options/snapshots` | ✅ 2026-11 (ADR 0008) — the daily IV snapshot, called by `.github/workflows/iv-snapshot.yml` after each US close and once more that night. For `OPTIONS_SNAPSHOT_SYMBOLS` plus recently viewed symbols (≤ 30): one row per ticker for the last completed session (`market_calendar`), insert-only; `market_open` while quotes move, `no_new_session` when everything is stored. No DB connection held during the Yahoo fetch; fetch and math on the options thread; a second Yahoo throttle defers the rest; 300 s budget; 409 when a run is already going. Auth-gated. |
| Options page | `GET /v1/options/{symbol}`, `GET /v1/options/{symbol}/chain/{expiry}` | ✅ 2026-11 (ADR 0008) — `options_report`: one build reads a stock's earnings schedule (`earnings_calendar`, cached a day), the chains of the expiries `options_analysis.report_expiries` picks (targets from 7 to 365 days, the snapshot's, and two each side of a report) and two years of closes, all on the options thread; then the stored IV30 history (percentile from 63 sessions, rank from 126) and the view recorded in `options_tracked` (not with `?track=false`, which the positions page sends so the owner's holdings aren't recorded). Returns the term structure and expected-move cone (each expiry read with its max pain and net gamma exposure), the chain nearest 30 days (smile, near-money rows, open interest by strike, and its positioning from `options_positioning`: call/put totals, the 10 largest contracts, max pain, net gamma and delta exposure by strike, the walls, the gamma flip), put/call ratios, the implied earnings move (`options_earnings`: per-session variance plus the report's, refused with the reason when the expiries are too far) and the last 8 reports' moves, plus claims with units. Cached 15 min (6 h for no options), 30 symbols, stale on failure, 503 with nothing cached; 404 for an unknown symbol or unlisted expiry; cache misses rate-limited per IP (`OPTIONS_RATE_LIMIT_PER_HOUR`, 60). Auth-gated. |
| Options read | `GET /v1/options/{symbol}/read` | ✅ 2026-11 (ADR 0008, PR5) — `options_read`: a headline and 3–5 points the model writes from the report's claims (comparisons carry their direction in words from `options_analysis`); each point cites the claims it quotes, code drops a point quoting a number no claim shows and a headline with one spoils the read. Returns the claims it cites from. Cached per symbol and quote time (30); 404 when there's nothing to read, 503 when no read survives; reads the model has to write rate-limited per IP (`OPTIONS_READ_RATE_LIMIT_PER_HOUR`, 20), a report build counting as a lookup. Auth-gated. |
| Owner | `GET /v1/owner/status`, `GET /v1/owner/positions`, `GET /v1/owner/trades`, `GET /v1/owner/trades.csv`, `GET /v1/owner/options/{symbol}/live/{expiry}`, `GET /v1/owner/options/{symbol}/history`, `GET /v1/owner/options/{symbol}/chain` | ✅ 2026-11 (ADR 0009, amended) — the owner's account routes, behind the shared secret and `X-Owner-Key` (`require_owner`; 404 with `OWNER_KEY` unset, 403 on a wrong key, a per-IP lockout after `OWNER_KEY_FAILURES_PER_HOUR` wrong ones), left out of the OpenAPI schema. `status` says whether tastytrade is configured. `positions` (`owner_positions`): the owner's accounts and positions from tastytrade, OCC symbols parsed, live REST quotes (mark, IV, Greeks) 100 symbols a call, grouped by underlying (stock legs included), futures and unreadable rows listed as not analysed; 15 s in memory, the last copy marked stale when tastytrade fails, 503 with the reason when there's none; `Cache-Control: no-store`; never stored; accounts numbered, never named. `trades` (`owner_trades`): the owner's transactions synced into `owner_transactions` (at most once a minute: a week back from the newest stored, the whole history first in each process and once a day, every page, new ones sealed by `owner_vault`, estimated fees replaced once final, no connection held during the fetch), then listed newest first with signed amounts; tastytrade down serves the copy with the reason; 503 without `OWNER_VAULT_KEY`. The trades come with their journal (`trade_journal`, computed each visit, never stored): FIFO lots per account and contract, positions by the order that opened them, each named from its legs (`trade_structures`), how it ended (closed, expired, assigned, exercised), realized P&L with fees, rolls linked, stock from an assignment as its own position, and what can't be matched listed with the reason. `trades.csv`: the copy as CSV, formula-like text defused. `options/{symbol}/live/{expiry}` (`owner_live_chain`): one expiry at tastytrade's live quotes. The strikes come from tastytrade's nested chain (standard deliverables, kept as plain rows, the last 4 symbols for 10 min) and the quotes for the 40 strikes either side of the price; the forward, our own IVs, the smile and positioning come from the same code as Yahoo's chain. It's 10 s in memory, one build per symbol and expiry, a 30 s deadline, 422 for an expiry tastytrade doesn't list (not 404: the page reads a 404 as "no owner key"), never stored, and never sent to the options read. `options/{symbol}/history` (`owner_iv_history`): ten years of tastytrade's daily candles (IV from about 2016) with each session's close, IV and 20-session realized volatility, where today's IV sits in the last year, and tastytrade's market metrics (IV index, IV rank and percentile, 30-day IV, 30/60/90-day historical volatility, all as fractions). It's 15 minutes in memory for at most 8 symbols, one build per symbol, a 45 s deadline, and 422 when tastytrade has nothing for the symbol. `options/{symbol}/chain` (`owner_whole_chain`): every expiry out to 120 days, strikes within 15% of tastytrade's price, quotes and open interest over DXLink in one session each (subscribed 500 at a time; SPY is about 4,800 contracts), each expiry through `options_metrics.smile` and `options_analysis.expiry_summary` (its ATM IV, expected move, max pain and net gamma), and the positioning added up across them (`options_positioning.across`: open interest, gamma and delta exposure by strike, the chain's walls and gamma flip; no max pain, which is one expiry's). At most 6,000 contracts, nearest expiries first; a minute in memory for at most 4 symbols; one build per symbol; a 60 s deadline; 422 when tastytrade lists no options. |
| Lenses | `GET /v1/lens`, `GET /v1/lens/{id}` | ✅ 2026-11 (ADR 0007 layer 3) — cross-company lens built from SEC XBRL annual filings (`xbrl.py`: tag merging per year, SEC calendar frames, 24 h disk cache) and `lens.py` (10-year window ending at the latest year every company filed; per-year distribution stats; computed facts; cited AI narrative). Each lens is one metric (`lens_catalog.py`: XBRL tags, label, definition) across a group; a company that never tagged the metric is left out and named. Lenses: megacap capex, stock-based compensation and R&D (without Amazon, which tags no R&D). In-memory cache 24 h, stale on failure, 503 when nothing cached. Auth-gated. |

## Frontend routes (current)

Lazy-loading is the binding bundle constraint — the main chunk must stay under 100 KB gzipped (current sizes: [frontend/README.md](../frontend/README.md)). Every authenticated route except `/` is split into its own chunk so the entry stays lean.

| Route | State | Chunk |
|---|---|---|
| `/login` | ✅ Pre-auth screen. Links to the demo when there is one. | main |
| `/demo`, `/demo/:ticker` | ✅ Public read-only demo, no sign-in: an index of the demo tickers and the same dashboard, read through `/v1/demo`. No sidebar, search, market strip, Regenerate or watchlist. | **lazy** (shell + index; the dashboard chunk is shared) |
| `/` | ✅ LandingPage — search bar + Past Reports (Watchlist and Recent live in the sidebar on every page). | main |
| `/symbol/:ticker` | ✅ The dashboard: sticky section nav, HeroCard, AnalystViewCard, full-width Quality / Earnings / Valuation / Per-share growth, an equal-height row of Cash & capital · Capital returns · Risk · Macro (only the cards with data), Insider activity, Business + News. | **lazy** |
| `/compare?a=X&b=Y` | ✅ Phase 4.6.A — two-ticker side-by-side. One % change price chart, growth by metric, risk on one scale. | **lazy** |
| `/lens`, `/lens/:id` | ✅ ADR 0007 layer 3 — cross-company lenses: the yearly distribution of a metric across a group (DistributionChart), dollars by company (AmountBars), a latest-year table and a cited AI read; headings and columns name the lens's metric. | **lazy** |
| `/options/:ticker` | ✅ ADR 0008 — every panel and tile explained: a takeaway sentence written in code from the report's figures (`lib/options-text.ts`, figures in bold), a stats table and a ⓘ; the expiry picker names days left and weekly/monthly (`expiryKind`: the third Friday, the Thursday before on Good Friday or Juneteenth); headline tiles (IV30 vs RV20, IV history percentile or "collecting", expected move, 25Δ skew, put/call OI); the expected-move cone and term structure on a square-root day scale; the next report's implied move against the last 8 reports' moves (or why it's refused); one expiry at a time (smile, open interest, chain) with an expiry picker reading `/chain/{expiry}`; a cited AI read under the tiles (`/read`, chips from the shared `CitedPoints`); a strategy builder on that expiry (seven templates: long call or put, debit and credit verticals, iron condor; cost, max profit and loss, breakevens and the risk-neutral probability of profit at mid and at the natural price, and the payoff at expiry), its arithmetic in `lib/options-strategy.ts`, held to Python's figures by a golden file. With the owner key, a Live switch on the expiry reads it at tastytrade's live quotes (`/v1/owner/options/{symbol}/live/{expiry}`): the same charts, table and strategy builder priced live, refreshed every 15 s, labelled with the quotes' age; when live quotes fail the delayed chain stays, with the reason. With the owner key, an IV history panel reads `/v1/owner/options/{symbol}/history`: IV and RV20 over a year, three years or everything, a sentence placing today's IV in the past year, and tastytrade's own rank, percentile and HVs. It shows even when Yahoo's chain is one-sided overnight. Linked from the symbol page; not in the demo. Schemas and fetchers live in `lib/options-*.ts`, which only this chunk imports. | **lazy** |
| `/positions` | ✅ ADR 0009 (amended) — the owner's positions, behind the owner key on top of the sign-in: an unlock form (a hidden username so a password manager saves and syncs the key; posts; checks the key with `/v1/owner/status` before keeping it), then a card per underlying: legs at tastytrade's marks with each quote's age, Greeks in dollars (per 1% move, per day, per IV point), the payoff at the first expiry and in a what-if (price, IV, days; Black-76 in `lib/options-pricing.ts`, held to Python by the golden file), the risk-neutral chance of profit from that expiry's smile, how often five years of moves would have left it in profit, a report before expiry, max pain and the walls; totals across the page. Context from the options routes for the first 10 underlyings (each cold read spends one of the hour's options lookups), read with `track=false` under query keys of its own, so a later options-page visit still reaches the server and records the view; the held expiry's chain is asked for once the report is in, since the report often read it already. Each option leg is valued to its expiry's close as the server gives it (`expires_at`, from `market_calendar`: 4 pm New York, 1 pm on half days). Sentences in code (`lib/positions-text.ts`), no prompt; tastytrade's figures in memory only. A sidebar link shows when a key is stored; sign out clears it. Not in the demo. | **lazy** (shares a chunk with the options page) |
| `/trades` | ✅ ADR 0009 (amended) — the owner's transactions from the encrypted copy, behind the owner key: synced on each visit (the copy as it stands, with the reason, when tastytrade is down), newest first, filterable by underlying, signed net amounts and fees, and a Download CSV. In memory only (`gcTime: 0`); a sidebar link when a key is stored. Two tabs: a Journal (a sentence on what closed; realized P&L by month closed, hand-rolled SVG bars; the positions newest first, filterable by open or closed, each opening to its legs, origin, rolls and fills; what isn't matched, with why) and the Transactions table. | **lazy** |
| (overlay) `SearchModal` | ✅ Phase 4.7 — ⌘K-triggered. | **lazy** |

Errors are serialized as [RFC 7807 problem+json](https://www.rfc-editor.org/rfc/rfc7807) via [app/core/errors.py](../app/core/errors.py). The handler propagates `HTTPException.headers` so `Retry-After` (429) and `WWW-Authenticate` (401) survive the wrap.

## External Integrations (current)

| Service | Purpose | Failure mode |
|---|---|---|
| yfinance | OHLCV, fundamentals, peers, earnings, ten years of closes for the year-end multiples, option chains and `^IRX` (options; Yahoo's own IV column is never used) | Defensive `_safe_loc` lookups; missing fields become `None`-valued claims with stable shape |
| SEC EDGAR | Filings (10-K, Form 4, 13F-HR); XBRL company concepts for lenses and the ten-year per-share history | Disk-cached: filing texts forever (filings never change), the list of filings 12 h, XBRL 24 h. SEC lists a big filer's filings older than a year in extra pages (JPM files 26,000 a year); they are read, back three years, when the latest year doesn't hold enough. SEC `User-Agent` mandatory; every request in the process spaced through one lock (8 a second, under SEC's 10). A company that moved to a new registrant is read across both (`sec_registrants.py`). A ticker SEC doesn't know fails the SEC tools only; their cards drop out and the page says so |
| NewsAPI | News articles | Optional — skipped silently when `NEWSAPI_KEY` empty |
| FRED | Macro series | Optional — `fetch_macro` emits metadata claims with None values when `FRED_API_KEY` empty |
| tastytrade | The owner's account (ADR 0009): REST (`tastytrade_client`: chains, quotes, market metrics, the owner's transactions and positions) and DXLink (`dxlink`: candles, Summary, Greeks). A personal OAuth grant, `scope=read` (a token is used only when its scope is known and read-only), GET paths on an allowlist; DXLink only to tastytrade's feed host on 443, no redirects. So far only `python -m app.services.tastytrade_probe` reads it | Optional — off when `TASTYTRADE_CLIENT_SECRET` or `TASTYTRADE_REFRESH_TOKEN` is empty. `TastytradeUnavailable` after three tries (backoff on 429/5xx, one fresh sign-in on 401); a refused sign-in pauses every call for an hour |
| Anthropic Claude | Synth (Sonnet 4.6) + triage (Haiku 4.5) when `LLM_PROVIDER=anthropic` (default) | `RuntimeError` → 503 problem+json (key not configured / provider API error) |
| DeepSeek | Synth + triage (`deepseek-flash`, thinking disabled) when `LLM_PROVIDER=deepseek`. OpenAI-format API via the `openai` SDK (`app/services/llm_deepseek.py`) | `RuntimeError` → 503 problem+json (key not configured / provider API error, e.g. 402 out of credit) |

Every external call is logged via `log_external_call` (service id, input/output summary, latency ms, timestamp, outcome). See [security.md §A09](security.md#a09) for why.

## Architecture Decisions

ADRs in [docs/adr/](adr/):

- [0001](adr/0001-stack-choice.md) — FastAPI + async SQLAlchemy over Flask/Django.
- [0002](adr/0002-deployment.md) — Deploy to Fly.io + Postgres on Neon.
- [0003](adr/0003-pivot-equity-research.md) — Pivot from v1 (real-time multi-agent platform) to v2 (AI Equity Research Assistant).
- [0004](adr/0004-visual-first-product-shape.md) — Visual-first, delta-driven; not chasing Morningstar-narrative depth.
- [0005](adr/0005-symbol-centric-dashboard.md) — **Read this before proposing surface-shape changes.** Pivot from "click Generate → static report" to symbol-centric dashboard with adaptive layouts (Phase 4).
- [0006](adr/0006-pluggable-llm-provider.md) — LLM provider switchable per `LLM_PROVIDER` (Anthropic default, DeepSeek Flash).
- [0008](adr/0008-options-from-free-snapshots.md) — Options analysis from free yfinance chains on a separate page, our own IVs (Black-76 on a parity forward), and a daily IV snapshot by GitHub Actions cron.
- [0007](adr/0007-analytical-narratives.md) — Card prose interprets: derived comparison claims (`research_derived.py`), history in the prompt, sector-aware framing; citation rule unchanged.
- [0009](adr/0009-tastytrade-live-personal.md) — tastytrade as a live, personal, read-only source: never stored, never in a prompt or the demo, within its Open API terms.
