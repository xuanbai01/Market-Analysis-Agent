# Lessons

Every time a human (user, reviewer, PR comment) corrects Claude Code in this repo, capture the lesson here so it doesn't happen twice. Treat this file as an evolving rulebook.

## Format

Each entry has three parts:

```
### <short title>

**Date:** YYYY-MM-DD
**Context:** what I was doing
**Mistake:** what went wrong
**Rule:** the one-sentence takeaway I should follow next time
```

## Entries

### Heuristic value-formatters lie quietly until they meet an edge case

**Date:** 2026-05-03
**Context:** PR #50 (Strata 2-col layout) shipped. Dogfooding AAPL surfaced ROE rendered as `1.41` (no % suffix), capex/share rendered as `16.02%`, dividend yield rendered as `39.09%`.
**Mistake:** the frontend `formatClaimValue` heuristic — "any number with `abs <= 1` is a fraction; render ×100 + %" — looked correct and had been correct for every test fixture, but silently dropped the % suffix for fraction-form values ≥ 1 (Apple ROE = 141%) and silently rendered small per-share dollar amounts as percentages (capex = $0.16 → "16.00%"). Test fixtures all happened to use values where the heuristic gets it right. The bugs were invisible until a real high-ROE / dividend-paying / capital-light company hit production.
**Rule:** when a formatter has to pick between unit categories from a number's magnitude alone, it WILL be wrong eventually — annotate at the source (`Claim.unit: Literal[...]` on the producer side) so the formatter dispatches deterministically. If a heuristic must stay (back-compat for pre-annotation cached rows), keep it as the explicit fallback only — never the default for new code.

### Test fixtures don't dogfood — they reproduce the developer's mental model

**Date:** 2026-05-03
**Context:** Same PR-#50 dogfood. The bugs above had unit tests covering "renders X% for value 0.18" etc., but none for the edge cases that broke production.
**Mistake:** every fixture in `format.test.ts` happened to use values inside the heuristic's correct zone (margins as 0.18 / 0.745, market cap as 2.78e12). The "safe" fixtures masked three families of real-world bugs.
**Rule:** when writing tests for value-formatting / display-layer code, **deliberately seed an edge-case in each fixture set** — at minimum: a value > 1 that should still be a percent (high-ROE companies); a value < 1 that's a dollar amount (per-share metrics); and a value in percent-form (provider that returns `0.39` meaning "0.39%" rather than `0.0039`). One ticker that doesn't fit the developer's mental model is worth 10 happy-path fixtures.

### `candles` has FK → `symbols`; ingest paths must upsert the parent first

**Date:** 2026-05-03
**Context:** Phase 4.1's `GET /v1/market/{ticker}/prices?range=60D` returned HTTP 500 with `ForeignKeyViolationError` for any ticker not in the seed migration (NVDA, SPY) — i.e. ~every real-world ticker. The bug was masked in tests because every test fixture explicitly seeds `Symbol(symbol="NVDA")` before adding `Candle` rows.
**Mistake:** the prices route was added in PR #47 reusing `ingest_market_data`, which was originally only ever called after an explicit `POST /v1/symbols` had created the parent symbol row. The implicit precondition ("the symbol exists") was never tested for the cache-miss branch.
**Rule:** when adding a route that triggers a cache-miss → upstream-fetch → DB-write path for a primary key the user provides, always include a test where the symbol does NOT pre-exist in the parent table — the database FK is the only thing that catches the gap, and 500s in production are the worst place to discover it.
