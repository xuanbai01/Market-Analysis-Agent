# ADR 0004: Visual-First, Delta-Driven Report Shape

**Status:** Accepted
**Date:** 2026-04-29
**Deciders:** xuanbai01
**Refines:** [ADR 0003](0003-pivot-equity-research.md) — same product (AI Equity Research Assistant), same product scope, but a deliberate choice about *what shape the report takes* now that we've shipped a v1 of it and dogfooded several names.

## Context

Phase 2 shipped a working `POST /v1/research/{symbol}` with seven sections, ~50 citation-backed claims, and an LLM-written 2–4 sentence prose summary per section. Real-LLM golden eval passes at factuality ≥ 0.97. The frontend (Phase 3.0 + 3.1) shipped against this report shape and renders it as text-and-table cards.

After dogfooding several symbols (AAPL, NVDA, plus less-familiar names), the user surfaced a clear gap: **the report doesn't feel useful enough.** Specifically, it lacks the depth feel of a Morningstar/CFRA-style analyst note. Two reference points were named:

- **Traditional analyst narrative** — Morningstar, CFRA, Zacks. Long-form prose, bull/bear cases, multi-year DCF models, analyst opinion.
- **Modern data dashboard** — e.g. `profitviz.com/<TICKER>`. Multi-year time series rendered as charts, peer comparisons as visualizations, low text density.

This ADR captures the decision about which way to lean, and *why we are NOT chasing Morningstar-depth narrative*.

## What we have today vs why it feels shallow

The report's data is not actually shallow — Phase 2.1 ships ~50 claims spanning valuation, quality, capital allocation, earnings history (4 quarters), peers, 10-K risk-factor diff, and macro. The perceived shallowness comes from four things, none of which is "more data":

1. **No historical context.** "P/E 28.5x" tells you nothing without "AAPL has traded between 18x and 35x over the last five years." We have point-in-time numbers, not trends.
2. **No visual representation.** Even rich data lands flat as a tabular UI. A claim with a 5-year sparkline next to it is dramatically more informative than the same number in a table cell.
3. **Short prose.** The 2–4 sentence per-section summary was deliberate (less prose = less hallucination surface, see ADR 0003 §"Anti-hallucination disciplines"). It does not develop a thesis the way an analyst note does.
4. **No forward-looking projections.** We deliberately don't do these. DCF and 5-year revenue forecasts are exactly where LLMs hallucinate confidently. This is a constraint we keep.

## Options considered

### Option 1: Chase Morningstar-depth narrative

Add long-form analyst-style prose: bull case, bear case, multi-year financial projections, fair-value estimate with model assumptions, capital-allocation grade, ESG scores, etc.

- **Pros:** Closes the perceived "depth" gap most directly. Most familiar shape.
- **Cons:** Morningstar's value is *human analyst judgment refined over decades* + *proprietary multi-year DCF tradition*. Both are categorically not what an LLM with free tools can produce well. Going long on prose without genuine judgment behind it is exactly the "beautifully-formatted hallucination" failure mode ADR 0003 cuts.
- **Why rejected:** Wrong target for the toolkit available. We can produce *something that reads like* Morningstar; we cannot produce *something whose conclusions are as defensible* as Morningstar. Shipping the former without the latter is anti-portfolio — recruiters who know the space will recognize the gap immediately.

### Option 2: Lean modern visual-first (profitviz lane)

Add multi-year time series for every metric we already collect, render them as charts inline, surface deltas (quarter-over-quarter, year-over-year) explicitly. Reduce dependence on prose; let the data speak via visual representation. LLM commentary stays short and is reserved for genuinely judgment-dependent moments (10-K risk-factor changes, peer outliers, "what changed since last quarter").

- **Pros:** The data is mostly already free (yfinance gives ~5y quarterly history, FRED gives long series, EDGAR is cumulative). Visual rendering is mechanical — Recharts or similar is ~20 lines per chart type. *Preserves citation discipline* — every chart point is still a `Claim` with a `Source`. *No new hallucination surface*. Plays to the resume framing — "structured data assembly + visual synthesis" beats "LLM writes longer paragraphs."
- **Cons:** Frontend work scales linearly with chart complexity. Multi-year history complicates the schema (every Claim potentially carries a time series). The cache row gets bigger.
- **Why considered:** The biggest perceived gaps (no historical context, no visual representation) are exactly what this addresses, and addresses them in a way that *preserves* the anti-hallucination discipline rather than fighting it.

### Option 3: Narrative layer on TOP of visual depth

After Option 2 lands, add a narrative layer: explicit Bulls Say / Bears Say sections, "What Changed This Quarter" framing, catalyst awareness (earnings dates, recent material news). Each argument cites specific Claims (now including their historical points), so the LLM is constrained to argue from data we actually have.

- **Pros:** With multi-year history in place, the LLM has trends to argue *from* — bull/bear cases become substantive, not generic. Catalyst awareness leverages news-ingest infrastructure that already exists but isn't surfaced in reports today.
- **Cons:** Longer prose = more hallucination surface. Needs rubric extension — "every bull/bear bullet must reference at least one Claim ID" — to keep citation discipline intact.
- **Why considered as Option 2's follow-up:** Without Option 2's data depth first, this is just longer-winded versions of today's summaries. With Option 2 first, this is the thesis-development layer that closes the remaining gap to a Morningstar-shaped report — minus the multi-year DCF projections we're explicitly not doing.

### Option 4: Try to add depth purely via more LLM prose / more agent rounds

Have the agent run more tools, write longer summaries, possibly do multiple synthesis passes.

- **Pros:** No new schema, no new frontend work.
- **Cons:** Doesn't address the actual gaps. More prose with the same data underneath is more places for hallucination, not more analytical depth. Multi-pass synthesis costs more and the rubric improvements would have to compensate.
- **Why rejected:** This is the pattern that produces analyst-note simulacra — confident-sounding text without the underlying analytical substance. Exactly what ADR 0003 said no to.

## Decision

**Adopt Option 2 first (Phase 3), then Option 3 (Phase 4).** Reject Option 1 outright. Reject Option 4.

Phase 3 (visual-first depth) is the new active phase. Phase 4 (narrative layer) lands only after Phase 3 ships and the user has dogfooded enough to confirm the data foundation is right.

The previously-sketched "Phase 3" plan (`search_history` pgvector RAG + `compute_options` daily IV snapshots) is **demoted to indefinite future scope** — neither addresses the perceived-shallowness problem; both add complexity without compounding value.

### Phase 3 — Visual-first depth (the new active phase)

What it adds:

- **Multi-year historical time series** for the metrics we already report. yfinance exposes ~5 years of quarterly fundamentals (revenue, net income, gross margin, EPS), ~5+ years of price history (already collected for `compute_technicals`), and full earnings-date history via `Ticker.earnings_dates`. FRED series are inherently long. EDGAR filings accumulate naturally. The scope is roughly: extend existing tools to return history, not add new tools.
- **Schema extension** — `Claim.history?: list[ClaimHistoryPoint]` where `ClaimHistoryPoint = {period: str, value: float}`. Optional and backwards-compatible. A claim without `.history` renders as today; a claim with `.history` renders with a sparkline next to the current value.
- **Frontend visual layer** — sparklines inline in claim tables, larger time-series charts for sections that warrant it (price + technicals, fundamentals trend), peer-comparison scatter plots. Recharts is the chart library of choice (works well with React 18, lightweight, no canvas dependencies).
- **Derived historical metrics** — historical P/E, P/S, EV/EBITDA computed from price + financials over time. This is where "AAPL trades at 28x today vs a 5-year median of 26x" comes from. Derived, not fetched.

Non-goals for Phase 3:

- No new section types. The existing seven sections stay.
- No bull/bear narrative layer. That's Phase 4.
- No forward projections.
- No new tools (`search_history`, `compute_options`).

### Phase 4 — Narrative layer (deferred; lands after Phase 3 ships)

What it would add (subject to refinement when we get there):

- New section: explicit **Bulls Say** + **Bears Say** as bullet lists where each argument carries a `claim_refs: list[str]` field linking to specific Claims. Rubric extended to enforce: every argument must reference ≥1 Claim, and any number stated in the argument's rationale must appear in a referenced Claim's `value` or `history`.
- New section: **What Changed** — quarter-over-quarter and year-over-year deltas surfaced explicitly. With Phase 3's multi-year history, this becomes mechanical (compute deltas) rather than LLM-judged.
- **Catalyst awareness** — earnings dates from `fetch_earnings`, recent material news from `fetch_news`. These pipelines already exist; the gap is wiring them into the report's narrative.
- New focus: `?focus=thesis` for the bull/bear-oriented view, complementing existing `full` and `earnings`.

## What we deliberately keep from Phase 2

All of these are non-negotiable and continue to gate every new PR:

1. **Citation discipline.** Every claim cites the tool call that produced it. Charts render `Claim`s, not free-floating data points. A point on a sparkline carries the same source provenance as a tabular value.
2. **Per-section confidence.** Programmatically computed; never LLM-set.
3. **Eval harness.** Real-LLM golden eval continues to gate every PR. Phase 3 extends the rubric to verify history-bearing claims (e.g. "if the prose says 'P/E has risen from 22 to 28', both 22 and 28 must appear in the referenced Claim's `.history`"). Phase 4 extends it further for bull/bear citation.
4. **`last_updated` per data point.** Each history point carries its own `period` (e.g. `"2024-Q4"`); the freshness story stays explicit.
5. **Free data only.** No paid feeds. yfinance + FRED + EDGAR + NewsAPI free tier remain the corpus.

## Consequences

### Easier

- **Closes the perceived gap with what we actually have.** The data is already free; we just aren't surfacing it visually.
- **Maintains citation discipline as the report gets richer.** Charts derive from `Claim.history`; nothing new escapes the schema.
- **Honest portfolio framing.** "Built a structured-data dashboard with LLM commentary at judgment-dependent points" beats "LLM writes longer paragraphs." The former is a system-design story; the latter is prompting.
- **Phase 4 becomes substantive.** With trends in place, the LLM has things to argue *from* — Phase 4's narrative layer is meaningful, not just verbose.

### Harder

- **Schema evolution.** `Claim.history` adds a new optional field that every builder has to populate where it can. JSONB cache rows grow. Defensive parsing on the frontend (sparkline only renders if history is present) prevents breakage but is friction.
- **Frontend complexity.** Charts mean a charting library, mean responsive sizing, mean accessibility considerations. Manageable, not free.
- **Eval rubric extension.** "Numbers in the prose match values in `claims`" → "Numbers in the prose match values in `claims` OR points in `claims[*].history`." Implemented as a small extension to `_matches_claim`.

### Locked-in

- **No analyst-narrative chase.** We are not adding multi-year DCF projections, fair-value estimates, capital-allocation letter grades, or 5-page bull/bear essays. The toolkit (free data + LLM) is wrong for those. Going down that path would be a reversal of this ADR, requiring its own ADR.
- **Free data only.** Going paid (Polygon historical, S&P fundamentals data) is a budget conversation, not just a code conversation. Worth it only if a Phase 3 or Phase 4 requirement genuinely cannot be met with free data — currently no such requirement exists.

## Revisit when

- **Phase 3 ships and the report still feels shallow.** That's a signal that the gap is actually in the prose layer, not the data layer — pull Phase 4 forward (or rethink the prose constraints).
- **A specific recurring use case can't be answered with free-data history.** E.g. someone wants intraday options chains historically. That's a paid-data conversation, not a "make the report deeper" conversation.
- **A user query type repeatedly fails the eval after Phase 4.** Pivot the prompting / schema / tool composition. The rubric stays the source of truth.
- **Real users start using this.** Then the previously-deferred items (auth + per-user cost caps + Redis-backed rate limit + abuse logging) come back on the table — none are Phase 3 / 4 concerns.
