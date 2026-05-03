# ADR 0005: Pivot from Generated Report to Symbol-Centric Dashboard

**Status:** Accepted
**Date:** 2026-05-02
**Deciders:** xuanbai01
**Refines:** [ADR 0004](0004-visual-first-product-shape.md) — same product (AI Equity Research Assistant), same anti-Morningstar visual-first commitment, but a structural decision about *what shape the user-facing surface takes* now that Phase 3 has shipped and been dogfooded end to end.

## Context

Phase 3 (visual-first depth) shipped across PRs #35–#44 over the spring of 2026. Backend ships 19+ history-bearing claims spanning fundamentals, earnings, peers, and macro. Frontend renders sparklines, section charts, peer scatter. The eval rubric reads `Claim.history` so trend prose passes factuality.

The user dogfooded the stack locally against MSFT / NVDA / AMZN / AAPL / RIVN. Two things became clear simultaneously:

1. **The data is right.** Multi-year history landed where it was missing; visual representation is now there in every section that warrants one. ADR 0004's bet paid off — closing the perceived-shallowness gap was about depth + visualization, not more LLM prose.

2. **The container is wrong.** Even with rich data and charts, the **"click Generate → scroll a static, top-to-bottom report"** pattern feels like a generated artifact, not an analyst tool. profitviz / stockanalysis / finchat / stratosphere all converge on a *symbol-centric dashboard* shape — you navigate to a ticker URL, the page is a rich layout, and you explore. The user surfaced this directly: *"I do not think we should only make it like a click-generate report."*

This ADR captures the decision to rebuild the frontend as a symbol-centric dashboard, the reasoning, and the explicit scope of what survives from Phase 3.

## What "report" vs "dashboard" actually mean here

Concretely:

| Aspect | Report (current) | Dashboard (this ADR) |
|---|---|---|
| Entry point | Form: enter symbol + focus → click Generate | URL: `/symbol/NVDA` directly bookmarkable |
| Layout | One-column scroll, seven sections stacked | Multi-column grid, hero + supporting cards |
| Personality | Same template for every ticker | **Adaptive** — distressed names reframe to cash runway / burn / risk |
| Navigation | Past-reports sidebar, no in-page nav | Sidebar (Search / Compare / Watch / Recent), search modal with `⌘K` |
| Cross-ticker | None | `/compare?a=NVDA&b=AVGO` page |
| News & business | Not surfaced | First-class (context band above quantitative sections) |
| Section narratives | Per-section LLM summary (2–4 sentences) | Same, plus **inline interpretations** ("Loss is narrowing. EPS −3.82 → −0.78 over 20Q — no positive print.") |
| Visual density | 7/10 (charts present but report-shaped) | 7/10 by default; toggleable to 9/10 (compact) |

The data story doesn't change. The presentation does, and the *interaction model* shifts from "generate a frozen artifact" to "explore a live ticker page."

## Why this is the right next step (and not a polish task)

The instinct is to call this a UI reskin — pick better colors, polish the charts, ship. That underestimates what "dashboard" means structurally. The Strata design that emerged from the user's prototyping session in Claude Design is doing four things the report shape cannot:

1. **Adaptive layouts.** A healthy company (NVDA) shows Forward P/E + ROIC + FCF Margin in the hero. A distressed company (RIVN) shows P/Sales + Cash Runway + Beat Rate, with an "UNPROFITABLE · TTM" pill in the chrome. Same backend data; different presentation rules picked by code (FCF margin negative → swap P/E for P/S; beat rate < 30% → flag bottom-decile; etc.). This isn't a feature you add to a static template — the template *is* the limitation.

2. **Cross-ticker comparison.** The report shape is intrinsically single-symbol. Compare mode (`/compare?a=NVDA&b=AVGO`) requires a different page treatment with valuation-vs-quality bars, overlay charts, and "what survives the compare / what's cut" framing.

3. **Sidebar persistence.** Search / Watchlist / Compare entry / Recent / Export are constant chrome regardless of what page you're on. The current dashboard component knows about one report at a time.

4. **Inline narratives that compose with cards.** "Disinflation continues; 10Y has compressed 43 bps from peak — modest tailwind for long-duration multiples" is a one-sentence interpretation rendered next to the macro chart. This is structurally different from a per-section summary block; it's a card-level companion that the report layout doesn't have a slot for.

Trying to retrofit any one of these into the existing report-renderer would require touching the same components we'd be rebuilding anyway. Honest accounting is: this is a frontend rewrite, not an extension.

## Options considered

### Option 1: Polish 3.3 in place

Keep the report shape; tighten typography, fix spacing, swap Recharts for a more polished chart library (visx / nivo), restyle the existing cards.

- **Pros:** Smallest scope. ~1–2 weeks. Existing component tree survives.
- **Cons:** Doesn't address the structural issues. After the polish ships, the same dogfooding session would produce the same complaint — "feels like a generated report, not a tool." Adaptive layouts, Compare mode, sidebar persistence are all still impossible without the structural rework.
- **Why rejected:** The visible problem (shallow visuals) has been solved by Phase 3. The latent problem (wrong shape) won't be solved by polishing a shape that's wrong.

### Option 2: Rebuild as a symbol-centric dashboard (Strata design)

Keep all backend work intact (Phase 2 + 3.1–3.4). Replace the frontend's report-renderer with a dashboard-shell layout: route-driven (`/symbol/:ticker`), grid-laid-out, sidebar-persistent, with adaptive presentation rules. Lift Sparkline + chart primitives from 3.3 as building blocks; replace SectionChart + PeerScatter + ReportRenderer + Dashboard.

- **Pros:** Closes the structural gaps directly. Adaptive layouts unlock the killer differentiator vs profitviz (their template is fixed regardless of company state). The user's existing Strata mockup is well-developed: token system, 9 semantic accents per metric category, hand-rolled SVG chart primitives, density toggle, and explicit treatments for healthy / distressed / compare. Most backend work survives untouched.
- **Cons:** ~8–10 weeks of frontend work, plus light backend work (OHLCV route, news wired into orchestrator, business descriptions, logo URL resolution). Some of Phase 3's frontend (SectionChart, PeerScatter, ReportRenderer) gets deprecated and replaced. Vercel deploy gets pushed back.
- **Why considered:** This is what the dogfooding session pointed to. The reference designs (profitviz, stockanalysis, finchat) all sit in this lane; the user's Strata mockup is a credible execution of it.

### Option 3: Build dashboard *alongside* the report (both endpoints stay)

Keep `POST /v1/research/{symbol}` and the report renderer as-is. Add `/symbol/:ticker` as a new dashboard route that consumes the same data with a different UI. Users pick which they prefer.

- **Pros:** No deprecation cost on Phase 3 frontend. Migration path is gentle.
- **Cons:** Two frontends to maintain forever. The "report" stops getting investment but stays in the codebase. Confused product surface — what is the canonical thing to show? Routes diverge over time as features land in only one. Doubles the surface area for the eval rubric (we'd want both paths to be factual).
- **Why rejected:** Splits product focus. The report shape was a Phase 2 starting point; the dashboard is the v3 surface. Maintaining both signals indecision rather than progress.

### Option 4: Pause frontend work, push the deferred Phase 4 (narrative layer) first

ADR 0004 § Phase 4 sketched a narrative layer: explicit Bulls Say / Bears Say with `claim_refs`, What Changed delta detection, catalyst awareness, `?focus=thesis`. Land that against the existing report, then revisit UI shape later.

- **Pros:** Higher analyst-output quality on the same UI. Plays to the LLM's strengths after Phase 3 gave it trends to argue from.
- **Cons:** Doesn't address the dogfooded complaint. A bull/bear case rendered in the existing report shape is *still* in the wrong container — the user ends Phase 4 with the same "it's a generated report, not a tool" gap. Also, the dashboard's adaptive-layout treatment for distressed names *already* delivers the most useful subset of "what changed / catalyst awareness" via inline narratives — without needing a separate Bulls/Bears section.
- **Why rejected:** Wrong sequence given dogfooding signal. The narrative-layer work is still valuable but lands as Phase 5, after the dashboard shape is in place and we know what's actually missing.

## Decision

**Adopt Option 2.** Phase 4 is the symbol-centric dashboard rebuild based on the Strata design.

Original Phase 4 (narrative layer — Bulls Say / Bears Say / What Changed / `?focus=thesis`) is renumbered to **Phase 5 (deferred)**. It's still on the roadmap but lands after Phase 4 ships and dogfooding confirms the structural gaps are closed.

Phase 3 work is **partially deprecated**:

- ✅ **Survives**: `Claim.history` schema, all 19+ history-bearing backend claims, the eval rubric's history-aware factuality matching, `Sparkline` (custom SVG), `ConfidenceBadge`, format helpers, auth flow, schema parsing.
- ❌ **Replaced**: `SectionChart`, `PeerScatter` (replaced by Strata variants with selectable axes), `ReportRenderer` (replaced by `SymbolDetailPage`), `Dashboard` shell (replaced by sidebar-persistent shell), the form-driven `/` flow (replaced by route-driven `/symbol/:ticker`).
- 🟡 **Restyled**: `LoginScreen`, `PastReportsList` (becomes "Recent" in sidebar).

Recharts dependency stays for now (it's already split into a shared chunk), but the Strata chart primitives are hand-rolled SVG, so Recharts may be eligible for removal at the end of Phase 4 if no chart needs it.

## Phase 4 sub-phase plan

The work is sequenced so each PR ships visible value, not "scaffolding only":

| Phase | Scope | Visible after |
|---|---|---|
| **4.0** | Token system + sidebar shell + route refactor (`/symbol/:ticker`) | Skeleton page exists at the new URL; styled chrome |
| **4.1** | Hero card (price chart + 3 featured stats) + Earnings card (EPS bars, beat rate) | Real data renders in the hero region for any ticker |
| **4.2** | Quality scorecard (3 rings + multi-line margins, hybrid 6+expand to 16) + Valuation matrix + PeerScatter v2 with selectable axes | Three of the seven primary cards complete |
| **4.3** | Per-share growth (rebased multi-line) + Cash & capital + Risk diff + Macro | All "static layout" cards complete |
| **4.4** | News integration (Haiku categorization + sentiment) + Business descriptions + section narratives (Sonnet inline interp) | Context band above quantitative sections; news-first product feel |
| **4.5** | Adaptive layout for distressed names | RIVN, F, RIVN-class names reframe automatically; the killer differentiator vs profitviz |
| **4.6** | Compare page (`/compare?a=X&b=Y`) | Cross-ticker comparison flow |
| **4.7** | Search modal (`⌘K`) + Watchlist (localStorage) + Recent ticker tracking | Sidebar functionality real, not chrome |
| **4.8** | Vercel deploy + dogfood gate | Public URL, real-eyes feedback, decision on Phase 5 vs polish |

Phase 4.0 + 4.1 alone replace the existing Generate-report shape with a real symbol-centric UI. Phases 4.2–4.4 build out the dashboard density. 4.5 is the differentiator. 4.6–4.7 are app-level features. 4.8 closes the loop.

Estimated total: 8–10 weeks at ~1 PR per phase per week. Some phases (4.3, 4.4) may split into two PRs.

## Backend work that lands alongside Phase 4

Most of Phase 4 is frontend, but a few backend pieces unlock visible product:

- **`GET /v1/market/:ticker/prices?range=60D`** — surface OHLCV for the hero price chart. Data already exists in `candles`; just no route. *Lands in 4.0 or 4.1.*
- **News integration in orchestrator** — `fetch_news` already exists (PR #13), just not wired into `compose_research_report`. Add a `_build_news` section + Haiku categorization (EARNINGS / PRODUCT / REGULATORY / M&A / SUPPLY) + sentiment classification at ~$0.0001 per headline. *Lands in 4.4.*
- **Business description** — yfinance `Ticker.info["longBusinessSummary"]` already accessible; one-liner addition to `fetch_fundamentals` or a new `fetch_business` tool. *Lands in 4.4.*
- **Logo URLs** — Clearbit (`logo.clearbit.com/<domain>`) or a static map. Cheap. *Lands in 4.0 or 4.1.*
- **Adaptive-layout signals** — flags the backend computes for "this is a distressed name": `distressed.is_unprofitable_ttm`, `distressed.beat_rate_below_30pct`, `distressed.cash_runway_quarters`, etc. These are derivable from existing claims; we add them to the response payload so the frontend doesn't need to recompute. *Lands in 4.5.*

What's NOT in Phase 4:

- Revenue mix by segment / geography (this was the deferred Tier 2 XBRL work; cards in the dashboard render "data not available" for now and become an explicit Phase 6 if dogfooding shows it's missed).
- Bulls Say / Bears Say (Phase 5 narrative layer).
- Multi-page tabs (Company / Financials / Valuation à la profitviz). The single-page Strata layout is denser; tabs are revisited only if dogfooding shows the page is too long.
- Mobile design. Desktop-first; mobile follows after dogfooding confirms the desktop product is right.

## What we deliberately keep from earlier phases

All non-negotiable from ADR 0003 + 0004:

1. **Citation discipline.** Every chart point on the dashboard derives from a `Claim` with a `Source`. The dashboard renders claims; it does not invent values.
2. **Per-section confidence.** Programmatically computed; never LLM-set.
3. **Eval harness.** The factuality rubric continues to gate every PR. Phase 3.4's history-aware matching applies to all chart-rendered numbers — if prose says "EPS rose from 1.40 to 2.18", both numbers must appear in the referenced claim's `value` or `history`.
4. **Free data only.** No paid feeds. yfinance + FRED + EDGAR + NewsAPI free tier.
5. **Anti-hallucination prose constraints.** Section narratives stay short (1–2 sentences) and reference Claims that exist in the data. No multi-year DCF projections, no fair-value estimates, no analyst grades.

## Consequences

### Easier

- **Bookmark a symbol.** `/symbol/NVDA` is a real URL. Users can share, bookmark, link.
- **Adaptive presentation.** The dashboard knows the difference between a profitable mature business and a cash-burning growth name. Every other tool in the lane has the same template for both.
- **Compare flow.** Two-ticker comparison was effectively impossible in the report shape. Now it's a route.
- **News + business in one place.** Currently news is fetched but not surfaced; business descriptions aren't surfaced at all. Both become first-class.
- **Cleaner product story.** "AI-powered equity research dashboard with adaptive layouts for healthy and distressed names" is sharper as a portfolio description than "research report generator."

### Harder

- **Frontend complexity.** Dashboard with sidebar + routing + search modal + compare is a real React application, not a single-page form.
- **Adaptive-layout test surface.** Each card variant for distressed names needs its own test coverage. We need fixture symbols at multiple "states" (healthy, slowing, unprofitable, distressed) to cover the layout matrix.
- **Migration path for cached reports.** Old `research_reports` JSONB rows still parse via Pydantic but the renderer that displays them changes shape. Cached rows from before Phase 4 may render with empty cards (we degrade gracefully where possible). The same-day cache lifetime (≤7 days) means this washes out within a week of any deploy.
- **Vercel deploy gets pushed.** Phase 3.5 was "Vercel + dogfood." That now becomes Phase 4.8.
- **Documentation churn.** The README's screenshots, the design doc's user-flow description, and any external resume/portfolio writeups need updating after 4.8.

### Locked-in

- **No analyst-narrative chase.** ADR 0004's anti-Morningstar commitment continues. Phase 5 narrative layer is bounded by `claim_refs` discipline.
- **Free data only.** Paid data conversation only opens if Phase 4 dogfooding surfaces a need that free-data history can't satisfy.
- **Single-page-app on the symbol detail.** No tabs (Company / Financials / Valuation) within `/symbol/:ticker`. If page length becomes a problem, anchor links + smooth scroll first; tabs only as a last resort.
- **Dashboard, not platform.** This isn't a portfolio tracker, brokerage integration, or trading screen. It's research on one ticker at a time, with comparison as the only multi-ticker mode.

## Revisit when

- **Phase 4 ships and dogfooding still complains.** That's a signal the gap is in the product positioning (research-tool-for-whom?), not the UI shape. ADR 0006 territory.
- **A meaningful number of users hit page-length limits.** Anchor-link smooth scroll first; tabs only if anchor scroll is insufficient.
- **Adaptive layout's "distressed" classification consistently mis-fires.** The detection rules (FCF margin < 0, beat rate < 30%, runway < 6Q) are heuristics. If they classify a healthy cyclical as distressed during a trough, the rules need refinement.
- **Phase 5 (narrative layer) starts feeling redundant with section narratives.** The dashboard's inline-interp narratives may already do most of the analytical work Bulls/Bears would; if so, Phase 5 scope shrinks or merges into refinement of inline-interp prompts.
- **Mobile demand surfaces from real users.** Desktop-first is a deliberate choice for a research tool; if the user base wants mobile, that's a Phase 6 conversation.
