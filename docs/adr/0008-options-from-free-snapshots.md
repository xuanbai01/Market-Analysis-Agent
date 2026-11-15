# ADR 0008: Options analysis from free chain snapshots, with our own daily IV history

**Status:** Accepted
**Date:** 2026-11-15
**Deciders:** Project owner
**Partly supersedes:** [ADR 0004](0004-visual-first-product-shape.md)'s indefinite deferral of `compute_options`

## Context

The owner no longer needs the project as a portfolio piece; the goal now is
a tool they use. ADR 0003 named two real workflows: long-term value
diligence (main account) and options with quantitative grounding (small
account). The second was planned as `compute_options` (ADR 0003, tool #11)
and then deferred indefinitely by ADR 0004, because it did not fix the
report's perceived shallowness. That reason no longer applies: Phases 3–5
fixed the shallowness, and the options workflow is the one the tool does
not serve at all. The owner trades directional buys (long calls and puts)
and spreads (verticals, iron condors).

What free data allows, checked 2026-11-14:

1. **yfinance option chains work.** One `option_chain()` call returns the
   expiry list, the front chain and the underlying quote; each contract has
   bid/ask, volume, open interest and Yahoo's IV, about 15 minutes delayed
   in market hours (AAPL: 23 expiries out to 2029). On liquid names our own
   Black-Scholes IV from mid prices matched Yahoo's within 0.2–3 points near
   the money; Yahoo's IV on illiquid strikes was junk (up to 154%). A thin
   name (NUS) had almost no two-sided quotes; BRK-A lists no options.
2. **No free source has option history with IV.** Alpha Vantage marks its
   historical and realtime options endpoints Premium; Massive (formerly
   Polygon) gives IV and greeks only from its paid Options Starter tier;
   Tradier's sandbox has no greeks. IV rank and percentile therefore need a
   history we record ourselves, one row per ticker per trading day.
3. **History can't be re-fetched,** so the IV method must be right before
   the first row is written: a wrong time-to-expiry on a weekend inflates a
   7-day option's IV by about 8%, and dividend and delay mismatches bias
   every row.

## Options considered

### Option 1: Options claims inside the research report
- Pros: one surface; the analyst view could cite them.
- Cons: option quotes are 15 minutes delayed and change by the minute, while
  a report is cached up to 7 days; every options fix would bump
  `REPORT_VERSION` and rebuild every report.

### Option 2: Pay for data (Massive Options Starter, about $29 a month)
- Pros: vendor IV and greeks, two years of history.
- Cons: a recurring cost the owner chose to avoid; still no IV history
  before the subscription starts; locks the feature to one vendor.

### Option 3 *(chosen)*: A separate options page on free chains, and our own daily IV snapshot
- Pros: free; the page can refresh on its own 15-minute cadence; the
  snapshot starts compounding now.
- Cons: IV percentile is unavailable for the first months; Yahoo is an
  unofficial source; a daily job and a table to run.

## Decision

1. **A separate authenticated page, `/options/:ticker`,** backed by
   `GET /v1/options/{symbol}`, not part of the research report. It is not in
   the public demo (it calls a provider). No `REPORT_VERSION` bump and no
   golden eval: research reports don't change.
2. **Code computes every number** (ADR 0007), from our own IVs, never
   Yahoo's: Black-76 on a forward taken from put-call parity (which absorbs
   discrete dividends and the quote delay), out-of-the-money side per strike,
   time to expiry measured to the minute from the quote time (the last
   close outside market hours), NYSE sessions from a rule-based calendar.
   The method has a `method_version` stored on every snapshot row, and the
   raw near-money quotes are stored beside the derived figures, so a later
   method can be recomputed over the whole history.
3. **One daily job, not a scheduler.** A GitHub Actions cron calls
   `POST /v1/options/snapshots` after each US close, with a retry run later
   the same night. The run is idempotent (`ON CONFLICT DO NOTHING` on
   symbol and trading date, the first good row wins) and takes the trading
   date from the data, not the server clock. ADR 0003 cut Celery, Redis and
   the 15-minute firehose; one daily call needs none of them.
4. **The cron uses the existing shared secret,** stored as a GitHub Actions
   secret. Every route still depends on `require_shared_secret`; a narrower
   automation token waits for collaborators.
5. **Analysis, not advice.** The page shows what option prices imply
   (expected moves, IV against realized volatility, term structure, skew,
   earnings moves, and later a strategy payoff builder with risk-neutral
   probabilities). It never ranks or recommends a trade, and says the
   probabilities are risk-neutral and the data delayed.

## Consequences

### Easier

- The options workflow is served from the same codebase, discipline and
  citations as the rest.
- IV percentile and rank become possible after about 63 and 126 sessions of
  history; the stored raw quotes allow recomputing them under a new method.

### Harder

- A daily job to watch: a failed run is a lost day of history (the retry
  run and the idempotent design limit this).
- The shared secret now also lives in GitHub; rotating it touches Fly,
  GitHub and the browser.
- Another Yahoo dependency; a throttled run defers the remaining tickers.

### Locked-in

- The snapshot table's meaning: one row per (symbol, trading date), first
  good row wins, figures tagged with the method version that made them.

## Revisit when

- Yahoo's option endpoint breaks or throttles the daily run repeatedly: then
  a paid source is a real conversation.
- The history shows the method needs a change: bump `method_version`,
  recompute from the stored quotes, and rank only rows of one version.
- Someone other than the owner gets access: a narrower token for the cron.
