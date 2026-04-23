# Market Analysis Agent — Product Requirements Document

**Author:** <your name>
**Date:** <YYYY-MM-DD>
**Status:** Draft / Approved / Shipping

<!-- The long-form design lives in `design_doc.md` at the repo root. Use this template
     when scoping a specific feature / release, not for the whole product. Copy to
     docs/PRD-<feature>.md or docs/PRD.md as appropriate. -->

## 1. One-line pitch

<!-- What this feature/release does, in one sentence a non-technical friend could understand. -->

## 2. Problem

<!-- What pain are we solving? Cite specific evidence — interviews, trading-desk feedback, design_doc.md section numbers, or user requests. Avoid "traders want better insights" abstractions. -->

## 3. Who is this for

<!-- Concrete persona(s). For the core product this is retail/prosumer traders doing self-directed analysis on US equities; pick a narrower slice for each release. -->

## 4. What makes this different

<!-- Existing alternatives (Bloomberg Terminal, TradingView, Seeking Alpha, other agents) and what gap this release fills. "Better UX" is not a gap. -->

| Alternative | Gap it leaves |
|---|---|
|  |  |
|  |  |

## 5. User stories

<!-- 3–8 stories for this release. Each maps to one or more sprint tasks. -->

1. As a <persona>, I want to <action>, so that <outcome>.
2.
3.

## 6. Acceptance criteria

<!-- Concrete, testable conditions per story. These become test cases. -->

### Story 1
- [ ]
- [ ]

### Story 2
- [ ]
- [ ]

## 7. Out of scope (this release)

<!-- Be explicit about what this release will NOT do. Saves arguments later. -->

-
-

## 8. Success metrics

<!-- At least one leading indicator (changes per user action) and one outcome metric. -->

- Leading indicator:
- Outcome metric:

## 9. Technical approach (high-level)

<!-- Not architecture — just the shape of the solution. Refer to `design_doc.md` and `docs/architecture.md` for the full system. Call out which services/routers/models change. -->

## 10. Cost impact

<!-- Relevant for this project because we're budget-constrained ($50-80/mo). Estimate the monthly cost delta: new LLM calls, new data provider tiers, storage growth, vector DB usage. -->

- Expected delta: $<X>/mo (<brief rationale>)

## 11. Risks and unknowns

-
-

## 12. Milestones

| Date | Milestone | Status |
|---|---|---|
|  | PRD approved | |
|  | First end-to-end flow working | |
|  | Beta with N users | |
|  | Release | |

## 13. Launch checklist

- [ ] All user stories have passing tests (see `docs/testing.md`)
- [ ] End-to-end flow walked manually against a fresh stack
- [ ] `/security-review` run on the branch
- [ ] Every new external call logged per `docs/security.md#a09` (service id, input, output, latency, timestamp)
- [ ] Rate limiting on any LLM-backed or paid-external-call endpoints
- [ ] ADR written for any architecturally significant decision in `docs/adr/`
- [ ] Cost impact confirmed vs. budget
