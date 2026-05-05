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

### Pre-push lint must mirror what CI runs, not what feels close

**Date:** 2026-05-04
**Context:** PR #54 broke the CI pipeline on `ruff check app tests` (an I001 import-block violation in `tests/test_risk_categorizer.py`) — even though I'd run `ruff check app` locally and seen "All checks passed!"
**Mistake:** I matched the *spirit* of the lint check (lint the backend code) but not the *letter* of the CI command (`ruff check app tests` — both directories). The test file's import block had a stylistic violation I'd written when first scaffolding the file in PR #52's RED commit; it survived merge because no human ran ruff against `tests/` afterwards.
**Rule:** verification commands must match CI verbatim, not "the equivalent." The repo's `docs/commands.md` says `uv run ruff check app && uv run pytest -v` is the pre-push sanity check; CI runs `uv run ruff check app tests`. When the two diverge, fix the docs and use the CI command. Never substitute "I ran ruff on the part I changed" for "I ran the full CI lint."

### Vite dev server in `.claude/worktrees/...` doesn't pick up file mtime changes reliably

**Date:** 2026-05-04
**Context:** PRs #58 and #59. Running the live preview to verify visual behavior of new code, the dev server kept serving the *previous* version of the modified file even after page reloads, server restarts, browser cache clears, and explicit `touch` on the source file. `fetch('/src/components/SymbolDetailPage.tsx')` returned the stale module body. The unit tests passed; the production `vite build` produced a correct bundle; only the dev server was stuck.
**Mistake:** spent ~15 minutes per PR debugging Vite's HMR cache assuming I'd written something wrong, when the tests had already proved I hadn't.
**Rule:** when working in a `.claude/worktrees/...` worktree, the Vite dev server's file watcher misses mtime updates on edits — likely a Windows + worktree-junction interaction. **Trust the unit tests + `vite build` for verification when preview shows stale content.** Don't keep restarting the dev server hoping it'll pick the change up. Document followup: investigate `server.watch.usePolling: true` in `vite.config.ts` as a long-term fix; for now, working around it in tests is fine because every visible-DOM contract is testable with happy-dom + `data-testid` markers.

### Inverting healthy-default flags to "non-default" before re-deriving is the trust-the-cache rule

**Date:** 2026-05-04
**Context:** PR #57 (Phase 4.5.A). The `backfill_layout_signals` helper for cached pre-4.5 reports needed to handle two cases: (a) a true pre-4.5 row, where `layout_signals` defaulted to healthy and the dashboard would render wrong unless we re-derived from the section claims; (b) a post-4.5 row, where `layout_signals` was already populated by the orchestrator and re-deriving might *clobber* it (e.g. if section claims somehow returned different data on a cache hit, or if the row had legitimately distressed signals from the original generation but empty section claims today).
**Mistake:** initial implementation re-derived unconditionally and compared input to derived. Test case "report with empty sections + populated distressed signals" caught it: the re-derive returned all-healthy (no claims to derive from), then I'd model_copy with the all-healthy signals, *overwriting* the populated distressed ones.
**Rule:** when backfilling a default-bearing field on cached data, the rule is "only re-derive when current matches the healthy default; otherwise trust the cache." A populated value (any non-default value, regardless of how it got there) is signal that someone — orchestrator or prior backfill — already did the derivation; replacing it with a fresh derivation can only ever be a net loss when the fresh derivation has less data to work with than the original.

### Section reorder via JSX prop spread doesn't propagate `data-*` attributes cleanly

**Date:** 2026-05-04
**Context:** PR #58 (Phase 4.5.B). Initial implementation of the row 3/4 reorder built two row JSX elements (each with `data-row` + `data-row-content`) and tried to "rewrap" them in slot divs by reading `top.props["data-row-content"]` and `top.props.children`. The browser rendered the cards but the `data-row-{3,4}` slot markers never appeared — querying the DOM for them returned 0 elements, and the reorder logic was effectively a no-op.
**Mistake:** assumed React's `props` object would expose `data-*` attributes set on the JSX element verbatim. In practice React strips/transforms some attributes during reconciliation (especially when the component being read is later spread back into JSX), and reading them back from a JSX node isn't a stable contract.
**Rule:** for slot-rotation patterns (where you want N JSX subtrees and a separate "which slot is each in" decision), pick the slot label *outside* the JSX subtree and pass it via a wrapper div, not by reading props off the inner element. The cleaner pattern is `<div data-row="..." data-row-content={isDistressed ? "X" : "Y"}>{isDistressed ? rowX : rowY}</div>` — explicit, statically inspectable, and React doesn't have to round-trip the data-attrs through reconciliation.

### Don't shadow `Number.isFinite` with a local helper of the same name

**Date:** 2026-05-05
**Context:** PR #61 (Phase 4.6.A). `CompareMetricRow.tsx` declared a local `isFinite(v: number | null): v is number` type-guard helper and then called it on `cell.valueA` / `cell.valueB`. TypeScript refused to narrow the property reads inside the surrounding function — even though the type guard was correct on the temporary local — and emitted four `Type 'null' is not assignable to type 'number'` errors. The fix wasn't the narrow logic; it was the name collision. JS hoists `function isFinite(...)` to the file scope, where it shadows the global `Number.isFinite` reference inside the helper itself. After renaming the local to `isFiniteValue` and switching to `const a = isFiniteValue(cell.valueA) ? cell.valueA : null;` (capturing the narrowed value into a local before doing arithmetic), tsc went green.
**Mistake:** named a local helper after a global it transitively depends on, AND assumed TypeScript would narrow a property read from a guard called on the property. Both are real but separate traps that compound when they collide.
**Rule:** (a) never name a local function the same as a built-in you call inside it — `Number.isFinite`, `Boolean`, `Array.isArray`, `String`, etc. (b) when narrowing a `T | null` property, capture the narrowed value into a `const` local before the operation; type guards on the property itself don't propagate across the surrounding function's flow analysis the way they do on a local variable.
