# ADR 0007: Card prose interprets the data, from comparisons computed in code

**Status:** Accepted
**Date:** 2026-11-08
**Deciders:** Project owner

## Context

Dogfooding the deployed dashboard (KO, 2026-11-08), the owner's verdict on
the cards: they display numbers but say nothing. The Quality summary read
"ROE of 40.59%, operating margin of 33.37%, gross margin of 62.32%…" — a
list of what the card already shows.

The cause is in what the synthesis call receives, not the model:

1. **Snapshot values only.** `_format_claim_line` sent `description = value`.
   `Claim.history` (5–20 periods for most metrics) never reached the
   prompt, so the model could not describe a trend.
2. **Nothing to compare against.** No change over time, no gap to peers, no
   relationship between metrics (does free cash flow cover the dividend? how
   long would operating cash flow take to repay net debt?).
3. **Comparisons the model works out itself fail the factuality rubric.**
   "Margins up 1.7 pts" is a number no claim holds, so it scores as a
   hallucination. Restating snapshots was the only safe output.
4. **The instructions asked for a summary** and forbade editorializing.

ADR 0004 chose visual-first over Morningstar-style narrative depth, and
ADR 0005 deferred a narrative layer (Phase 5) until dogfooding showed the
inline card prose falling short. It now has.

## Decision

Keep the existing surfaces (`summary`, `card_narrative`) and the
citation rule; change what the model is given and what it is asked for.

1. **Compute comparisons in code, as claims.** A pure module
   (`app/services/research_derived.py`) adds derived claims to each
   section, sourced `computed.analytics` with the formula in
   `Source.detail`. Examples: margin change between two named quarters,
   TTM free-cash-flow margin and yield, dividend payout and FCF coverage,
   capex intensity, net debt ÷ TTM operating cash flow, premium/discount to
   the peer median, EPS growth over the last four quarters vs the four
   before. Each is emitted only when its inputs exist and are meaningful
   (no ratio over a negative denominator), with its basis (TTM, which
   quarters) in the description.
2. **Send history.** Each history-bearing claim's prompt line carries its
   first and last points, low and high, and period count, in display units.
3. **Ask for interpretation.** The summary leads with the conclusion the
   data supports, backs it with the two or three comparisons that carry it,
   and names what to watch when the data shows a tension. It may not
   introduce causes, events, products or forecasts the claims don't
   contain, and it never computes a number the claims don't hold.
4. **Fix comparison sets that make comparisons wrong.** Consumer staples
   splits into branded staples (KO, PEP, PG, CL…) and staples retailers
   (WMT, COST, TGT…); a 60%-gross-margin brand was being measured against
   10%-margin warehouses.

Derived claims render in the existing tables ("Show all", the Capital
Allocation section) like any other claim, so every number in the prose is
still one click from its source.

## Consequences

- Prose can say "so what" while the factuality bar (≥ 0.97 on the golden
  set) still applies unchanged — the comparisons it cites are claims.
- More claims per section and history in the prompt: roughly 1.5–2× input
  tokens per synthesis call, still about a cent per report on DeepSeek.
- The derived formulas are now part of the product's analysis and need the
  same test discipline as the data tools. Where an input's basis is mixed
  (forward dividend vs trailing earnings), the description says so.
- Cached reports keep their old prose until regenerated
  (`ReportFreshness` → Regenerate).
- A report-level "Analyst view" (bull / bear / what changed, ADR 0005's
  Phase 5) and a cross-company distribution view (Phase 6, needs XBRL
  history) build on these derived claims later; they are not part of this
  decision.

## Follow-up (2026-11-09)

Layer 2 shipped: `ResearchReport.thesis`, the analyst view (headline, bull,
bear, what changed, what to watch). It is a second synthesis call over the
same claims, run in parallel with the section prose. Each claim is tagged
with an id in that prompt (`[Q3]`), points cite ids, and code keeps only
points whose ids resolve — so every argument links to its evidence on the
dashboard. The factuality rubric covers the thesis text.

