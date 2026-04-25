# ADR 0003: Pivot to AI Equity Research Assistant

**Status:** Accepted
**Date:** 2026-04-24
**Deciders:** xuanbai01
**Supersedes (in part):** [`design_doc.md`](../../design_doc.md) §1 (Project Scope), §2 (System Architecture client-list), §6 (Agent Roles), §12 (Roadmap). The infrastructure choices in v1 (FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, observability helper) carry forward unchanged — only the *product* pivots.

## Context

After Phase 1 shipped (live URL, real OHLCV ingest, technicals, deploy pipeline), we revisited whether the original v1 vision — a real-time multi-agent RAG platform with scheduled news firehose and a Discord bot — is the right v2.

Three things forced the rethink:

1. **Project goal alignment.** This is a portfolio + self-use project, not a product targeting active traders. Recruiters don't tour the freshness of a feed; they tour the depth of a single feature. Self-use is value-investing on a main account + small-account options trading — neither of which benefits from 15-minute news ingest.
2. **The data wall.** Real-time options data is paywalled at ~$200/mo across every credible vendor. An "options copilot" without live IV is restating definitions, which is not interview-bait.
3. **AI architectural shift since the v1 design.** "Multi-agent RAG" as a top-line architecture reads as 2023. By 2026 the resume-worthy patterns are *single agent + well-designed tools*, *MCP-style tool exposure*, *structured outputs with Pydantic*, *eval harnesses*, and *cost-tier routing*. Multi-agent orchestration is one *mode* inside that, not the architecture.

## Options considered

### Option 1: Stay the v1 course
- **Pros:** No re-scoping cost. Original ADR 0001 + 0002 still align.
- **Cons:** Generic "real-time market analysis platform" framing is hard to demo in 30 seconds, every infrastructure piece (Celery, Redis, Pinecone, scheduled cron, Discord bot) is dev work that doesn't compound into a single recognizable feature, and the multi-agent-as-architecture framing is dated.

### Option 2: Drop the project, start something narrower
- **Pros:** Clean slate.
- **Cons:** Throws away the live deploy, working ingest, technicals, observability, and tests. Phase 1 is genuinely useful infrastructure for a research-style tool — only the *output product* needs to change.

### Option 3 *(chosen)*: Pivot to "AI Equity Research Assistant" on the existing infrastructure
- Keep everything in Phase 1: FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, the `candles` table, the `log_external_call` pattern, the test harness, the deploy workflow, the 45-test suite.
- Pivot the *product*: from "real-time market platform with scheduled firehose" to **on-demand structured equity research reports**, free data only, single agent + tools by default, optional supervisor mode for complex queries.
- Two real workflows match the user's actual trading style: long-term value diligence (main account) and options education with quantitative grounding (small account).

### Option 4: A different narrow tool entirely (earnings prep / "why did this move")
- **Pros:** Even more specific, even more demoable.
- **Cons:** Doesn't reuse Phase 1 infrastructure as well. Earnings prep can be one *focus mode* of the research assistant rather than the whole product.

## Decision

**Pivot to AI Equity Research Assistant** with the scope below. Everything Phase 1 built is reused; the pivot is purely at the product layer (`app/services/agent.py` + new tools + revised endpoints).

### v2 product scope

**Single primary entry point:**

```
POST /v1/research/{symbol}
{
  "focus": "earnings" | "technical" | "full",   # optional
  "include_sentiment": false                     # optional, opt-in
}
```

Returns a Pydantic-typed structured report. Sections include valuation, quality, capital allocation, technicals, recent news + earnings synthesis, peer comparison, macro context, insider activity, institutional flows, risk-factor delta, short interest, and (where relevant) options-implied move.

**Two operating modes:**
- **Default — single agent + tools.** The agent picks which tools to call based on the focus and the symbol. Audit trail of tool calls captured for debugging and eval.
- **Supervisor mode** for complex queries (multi-symbol comparison, portfolio-level analysis). Delegates to specialist sub-agents (Research, Technical, Sentiment, Earnings). This is *one mode*, not the architecture.

### v2 tool registry

| # | Tool | Source | Status |
|---|---|---|---|
| 1 | `fetch_market` | yfinance (OHLCV) | ✅ done |
| 2 | `compute_technicals` | in-memory (RSI, SMA20/50/200) | ✅ done |
| 3 | `fetch_fundamentals` | yfinance.info + financials/balance_sheet/cashflow → valuation, quality, capital allocation, short interest, dividends | next |
| 4 | `fetch_news` | NewsAPI + RSS w/ symbol tagging | next |
| 5 | `fetch_edgar` | SEC EDGAR generic filing fetch | |
| 6 | `parse_filing` | LLM + parsers: Form 4 (insiders), 13F (institutions), 10-K Item 1A (risks), 10-K Item 1 (business) | |
| 7 | `fetch_earnings` | scrape transcripts + yfinance consensus EPS | |
| 8 | `fetch_macro` | FRED API w/ sector→series map | |
| 9 | `fetch_peers` | hybrid: hardcoded top-N + yfinance sector fallback | |
| 10 | `search_history` | pgvector RAG over our stored news + filings | |
| 11 | `compute_options` | yfinance `option_chain` → IV percentile, implied move, term structure | |

### Anti-hallucination disciplines (non-negotiable v2 success criteria)

A research-report agent that produces beautifully-formatted hallucinations is worse than no agent. These four are mandatory and gate every Phase 2 PR:

1. **Citation discipline.** Every claim in every report cites the tool call that produced it (`source: yfinance, fetched 2026-04-24T15:00:00Z`). The structured output schema enforces this — no free-form text, only typed `Claim { value, source, fetched_at }` records. If the agent cannot cite a value, it cannot include it.
2. **Per-section confidence.** Every section carries an explicit `confidence: "high" | "medium" | "low"` field, set programmatically based on data freshness, sparsity, and whether the agent had to fall back. A 5-day-old FRED reading is not surfaced as "high confidence."
3. **Eval harness with factuality rubric.** ~20 golden questions where we know the right answer (P/E for AAPL on date X, latest 8-K date for NVDA, etc.) auto-graded on factuality + structure adherence + latency. Runs on every PR. A regression in factuality fails the build.
4. **`last_updated` per data point.** Every value in every report carries the timestamp of the upstream fetch. Stale data does not masquerade as fresh.

### Cost discipline

- **Cost-tier routing.** Haiku (or equivalent small model) for tool-call planning; Sonnet (or equivalent capable model) for synthesis. Documented in a follow-up ADR with measured savings.
- **Per-symbol response cache.** Identical research requests within the same trading day return cached reports unless `?refresh=true`. Saves both LLM cost and Yahoo / EDGAR rate-limit budget.
- **Hard rate limit on `/v1/research/*`** before public exposure. Single client cannot trigger more than N reports / hour.

## What we cut

- **Real-time / 15-minute scheduled ingest.** Daily-or-on-demand only. No Celery, no Redis, no cron firehose.
- **Discord bot.** Defer indefinitely. The portfolio surface is the live API + Swagger UI + (later) a small web frontend.
- **Multi-agent as the architecture.** Demoted to an optional supervisor mode for genuinely hard queries.
- **`POST /v1/option-explain` as a top-level endpoint.** Without IV percentile + skew it was vocabulary recital. Folded into the research report's "options context" section, populated only when `compute_options` adds quantitative grounding (IV percentile, implied move).
- **Reddit / r/wallstreetbets as a Phase 2 deliverable.** Real signal is narrow (high-retail-attention names only) and noise is high. Moved to "future scope" — revisit if any specific user query genuinely benefits from it.

## What we keep

- **All of Phase 1 infrastructure.** FastAPI, async SQLAlchemy, Postgres on Neon, Fly.io, Alembic, observability helper, test harness, CI, push-to-deploy.
- **Free data only.** $50–80/mo design-doc budget remains generous; $5–15/mo is realistic with cost-tier routing + caching.
- **The v1 RAG vocabulary.** pgvector + time-weighted retrieval (`score × e^(-λ × hours_since)`) still applies — the corpus is filings + news instead of a real-time feed, that's all.

## Consequences

### Easier

- **Demoable in 30 seconds.** "Pick a symbol, get a structured analyst-style report citing every claim." Recruiters and friends understand it without preamble.
- **Real workflows you'll actually use.** Long-term value diligence on the main account; options education on the small account.
- **Modern interview talking points.** Single agent + tools, structured outputs, eval harness, cost-tier routing, observability, citation discipline. Each has 2–3 sentences of real backing.
- **Honest cost story.** "Built on free-tier infra and free data sources, ~$5/mo all-in" is more impressive than infra heroics.

### Harder

- **Free data is messy.** EDGAR's filing parsers are XBRL-heavy; transcript scrapers will break; FRED series have lag. The agent has to handle "I tried, here's what I got, here's what I couldn't get" gracefully — exactly what `confidence` and `last_updated` are for.
- **Citation discipline is friction.** Every tool has to return values with source metadata; the LLM has to be prompted hard to never invent. Worth it; non-trivial.
- **Eval harness has to actually exist.** It's easy to skip. Phase 2 PRs are blocked on it landing first.

### Locked-in

- **Single-agent-by-default.** Switching back to multi-agent-as-architecture is a Phase 3 conversation, not a quick reversal.
- **Free data only.** Going paid (Polygon, Refinitiv) is a budget conversation, not a code conversation, but the resume framing changes ("built on free data" is part of the pitch).

## Revisit when

- **Free-data fatigue.** If 3+ tools have flaky scrapers / dead sources, evaluate paid feeds for the worst offenders.
- **A query type repeatedly fails the eval.** Pivot tool composition, prompt strategy, or schema — but the eval rubric stays the source of truth.
- **The supervisor-mode flag never gets used in practice.** Cut it; honesty in the architecture > theoretical generality.
- **Real users start using this.** Add auth, real rate limiting, per-user cost caps, abuse logging. None of that is a Phase 2 concern.
