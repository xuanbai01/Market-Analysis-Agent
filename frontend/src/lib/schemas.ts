/**
 * Zod schemas mirroring the backend Pydantic models in
 * ``app/schemas/research.py``. They serve two purposes:
 *
 * 1. Runtime validation of API responses — if the backend ever drifts
 *    (renames a field, changes a type), the parse fails loudly here
 *    instead of crashing some component three layers deep with
 *    ``Cannot read property 'foo' of undefined``.
 * 2. Source of truth for TS types in the rest of the app — every
 *    component imports from this module so the contract is one place.
 *
 * If you change a schema here, update the corresponding Pydantic model
 * AND the matching test in ``frontend/src/lib/schemas.test.ts``.
 */
import { z } from "zod";

// ── Building blocks ──────────────────────────────────────────────────

export const ConfidenceSchema = z.enum(["high", "medium", "low"]);
export type Confidence = z.infer<typeof ConfidenceSchema>;

export const SourceSchema = z.object({
  tool: z.string().min(1),
  fetched_at: z.string().datetime({ offset: true }),
  url: z.string().url().nullable().optional(),
  detail: z.string().nullable().optional(),
});
export type Source = z.infer<typeof SourceSchema>;

// ClaimValue: number, string, boolean, or null. Matches the Python
// ``ClaimValue = float | int | str | bool | None`` union.
export const ClaimValueSchema = z.union([
  z.number(),
  z.string(),
  z.boolean(),
  z.null(),
]);
export type ClaimValue = z.infer<typeof ClaimValueSchema>;

// Phase 4.3.X — display-unit hint mirroring backend ``ClaimUnit``. The
// ``formatClaimValue`` helper in ./format.ts dispatches on this so a
// fraction-form ROE > 1 doesn't drop its % suffix and per-share dollars
// < $1 don't render as percentages. Optional + nullable so pre-4.3.X
// cached rows (where the field is absent) round-trip unchanged.
export const ClaimUnitSchema = z.enum([
  "fraction",
  "percent",
  "usd",
  "usd_per_share",
  "ratio",
  "count",
  "shares",
  "basis_points",
  "percentage_points",
  "date",
  "string",
]);
export type ClaimUnit = z.infer<typeof ClaimUnitSchema>;

// One point in a Claim's time series. ``period`` is an opaque string
// label (``"2024-Q4"`` / ``"2024-12"`` / ``"2024"``) — different tools
// emit different cadences and the renderer doesn't parse them. ``value``
// is strictly numeric: only floats sparkline, so strings/bools/null are
// rejected at the parse boundary (mirrors the backend's
// ClaimHistoryPoint validator).
export const ClaimHistoryPointSchema = z.object({
  period: z.string().min(1).max(32),
  value: z.number(),
});
export type ClaimHistoryPoint = z.infer<typeof ClaimHistoryPointSchema>;

export const ClaimSchema = z.object({
  description: z.string().min(1),
  value: ClaimValueSchema,
  source: SourceSchema,
  // Phase 3.1: optional time series alongside the point-in-time value.
  // Defaults to [] so a Claim payload from before Phase 3.1 (no
  // "history" key) parses unchanged. Frontend renders a sparkline when
  // ``history.length >= 2``, skips it otherwise.
  history: z.array(ClaimHistoryPointSchema).default([]),
  // Phase 4.3.X: optional display-unit hint. Truly optional (no
  // default) so pre-4.3.X cached rows (no ``unit`` key) parse with
  // ``unit === undefined`` and existing test fixtures don't have to
  // be updated. The formatter treats undefined and null identically —
  // both fall back to the legacy heuristic.
  //
  // 2026-11: a unit this build doesn't know (the backend added one and
  // deployed first) reads as null — the heuristic formatter — instead of
  // failing the whole report's parse.
  unit: ClaimUnitSchema.nullable().optional().catch(null),
});
export type Claim = z.infer<typeof ClaimSchema>;

export const SectionSchema = z.object({
  title: z.string().min(1),
  claims: z.array(ClaimSchema).default([]),
  summary: z.string().default(""),
  confidence: ConfidenceSchema,
  // Phase 4.4.B — per-card 1-2 sentence punchy headline distinct from
  // ``summary`` (the broad 2-4 sentence narrative). Each dedicated card
  // (Quality / Earnings / PerShareGrowth / RiskDiff / Macro) renders
  // it as a strip at the bottom of the card body. Optional + nullable
  // (mirrors ``unit`` on Claim) so pre-4.4.B cached JSONB rows and
  // existing test fixtures parse without churn — the render check
  // (``narrative ? <strip /> : null``) handles undefined / null /
  // empty uniformly.
  card_narrative: z.string().nullable().optional(),
});
export type Section = z.infer<typeof SectionSchema>;

// ── Phase 4.5: LayoutSignals ─────────────────────────────────────────

// Per-flag defaults mirror backend ``LayoutSignals`` in
// ``app/schemas/research.py`` — every flag's "healthy" value is
// false / null. The schema allows a partial object (any missing flag
// fills in the healthy default) so a pre-4.5 cached payload OR a
// post-4.5 payload that omits a not-yet-shipped flag both parse cleanly.
export const LayoutSignalsSchema = z.object({
  is_unprofitable_ttm: z.boolean().default(false),
  beat_rate_below_30pct: z.boolean().default(false),
  cash_runway_quarters: z.number().nullable().default(null),
  gross_margin_negative: z.boolean().default(false),
  debt_rising_cash_falling: z.boolean().default(false),
});
export type LayoutSignals = z.infer<typeof LayoutSignalsSchema>;

/** Phase 4.5 — exported so test fixtures can spread the healthy
 *  default without re-typing every flag. Production code rarely needs
 *  this since parsed payloads always have ``layout_signals`` populated;
 *  tests construct raw object literals so they need the constant. */
export const HEALTHY_LAYOUT_SIGNALS: LayoutSignals = {
  is_unprofitable_ttm: false,
  beat_rate_below_30pct: false,
  cash_runway_quarters: null,
  gross_margin_negative: false,
  debt_rising_cash_falling: false,
};

// ── Top-level shapes returned by the backend ─────────────────────────

// Phase 5 — the analyst view. Mirrors Thesis in app/schemas/research.py.
// A claim_ref points at report.sections[title].claims[index].
export const ClaimRefSchema = z.object({
  section: z.string().min(1),
  index: z.number().int().min(0),
});
export type ClaimRef = z.infer<typeof ClaimRefSchema>;

export const ThesisPointSchema = z.object({
  text: z.string().min(1),
  claim_refs: z.array(ClaimRefSchema).default([]),
});
export type ThesisPoint = z.infer<typeof ThesisPointSchema>;

export const ThesisSchema = z.object({
  headline: z.string().min(1),
  bull: z.array(ThesisPointSchema).default([]),
  bear: z.array(ThesisPointSchema).default([]),
  changed: z.array(ThesisPointSchema).default([]),
  watch: z.array(ThesisPointSchema).default([]),
});
export type Thesis = z.infer<typeof ThesisSchema>;

export const ResearchReportSchema = z.object({
  symbol: z.string().min(1),
  generated_at: z.string().datetime({ offset: true }),
  sections: z.array(SectionSchema).default([]),
  overall_confidence: ConfidenceSchema,
  // ``tool_calls_audit`` is debug-only — backend may stop emitting
  // it in a future change. Optional + default so we don't break.
  tool_calls_audit: z.array(z.string()).default([]),
  // Phase 4.1 — top-level metadata for the hero card. Both default
  // to null on backwards-compat with pre-4.1 cached reports.
  name: z.string().nullable().default(null),
  sector: z.string().nullable().default(null),
  // Phase 4.5 — adaptive-layout signals. Defaults to healthy so
  // pre-4.5 cached JSONB rows hydrate as a healthy report and the
  // dashboard's adaptive UI stays in its non-distressed mode.
  layout_signals: LayoutSignalsSchema.default(HEALTHY_LAYOUT_SIGNALS),
  // Phase 5 — null for reports from before the analyst view shipped, or
  // when its call failed. A malformed thesis reads as null rather than
  // failing the whole report.
  thesis: ThesisSchema.nullable().default(null).catch(null),
});
export type ResearchReport = z.infer<typeof ResearchReportSchema>;

export const ResearchReportSummarySchema = z.object({
  symbol: z.string().min(1),
  focus: z.string().min(1),
  // backend serializes report_date as YYYY-MM-DD (Pydantic Date),
  // not full ISO datetime. Keep as a plain string here.
  report_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  generated_at: z.string().datetime({ offset: true }),
  overall_confidence: ConfidenceSchema,
});
export type ResearchReportSummary = z.infer<
  typeof ResearchReportSummarySchema
>;

export const ResearchReportSummariesSchema = z.array(
  ResearchReportSummarySchema,
);

// Phase 4.1 — hero price chart endpoint shape mirroring
// MarketPricesOut in app/schemas/market.py.
export const PricePointSchema = z.object({
  ts: z.string(),
  close: z.number(),
  volume: z.number(),
});
export type PricePoint = z.infer<typeof PricePointSchema>;

export const PriceLatestSchema = z.object({
  ts: z.string(),
  close: z.number(),
  delta_abs: z.number(),
  delta_pct: z.number(),
});
export type PriceLatest = z.infer<typeof PriceLatestSchema>;

export const MarketPricesSchema = z.object({
  ticker: z.string().min(1),
  range: z.string().min(1),
  prices: z.array(PricePointSchema).default([]),
  latest: PriceLatestSchema,
});
export type MarketPrices = z.infer<typeof MarketPricesSchema>;

// Market strip — mirrors MarketOverview in app/schemas/market_overview.py.
// Units and ratings fall back instead of failing, so a value added on
// the backend can't blank the whole strip.

export const QuoteUnitSchema = z.enum(["points", "percent", "usd"]).catch("points");
export type QuoteUnit = z.infer<typeof QuoteUnitSchema>;

export const MarketQuoteSchema = z.object({
  symbol: z.string().min(1),
  label: z.string().min(1),
  kind: z.string(),
  unit: QuoteUnitSchema,
  price: z.number(),
  change: z.number(),
  change_percent: z.number(),
  as_of: z.string(),
});
export type MarketQuote = z.infer<typeof MarketQuoteSchema>;

export const SentimentRatingSchema = z
  .enum(["extreme_fear", "fear", "neutral", "greed", "extreme_greed"])
  .catch("neutral");
export type SentimentRating = z.infer<typeof SentimentRatingSchema>;

export const SentimentComponentSchema = z.object({
  key: z.string(),
  label: z.string(),
  score: z.number(),
  description: z.string(),
});
export type SentimentComponent = z.infer<typeof SentimentComponentSchema>;

export const SentimentEstimateSchema = z.object({
  score: z.number(),
  rating: SentimentRatingSchema,
  components: z.array(SentimentComponentSchema).default([]),
  as_of: z.string(),
  methodology: z.string(),
});
export type SentimentEstimate = z.infer<typeof SentimentEstimateSchema>;

export const MarketOverviewSchema = z.object({
  quotes: z.array(MarketQuoteSchema).default([]),
  sentiment: SentimentEstimateSchema.nullable().default(null),
  generated_at: z.string(),
});
export type MarketOverview = z.infer<typeof MarketOverviewSchema>;

// ── Focus enum (mirrors Focus in research_tool_registry.py) ──────────

export const FocusSchema = z.enum(["full", "earnings"]);
export type Focus = z.infer<typeof FocusSchema>;

// ── RFC 7807 problem+json error shape (from app/core/errors.py) ──────
//
// The backend emits this on every non-2xx response. We don't model it
// strictly because not every middleware in the stack respects the
// shape (FastAPI's built-in 422 from a query-validation failure has
// a different ``detail`` field), but ``title`` + ``status`` are
// reliable.
export const ProblemDetailSchema = z.object({
  type: z.string().optional(),
  title: z.string(),
  status: z.number(),
  detail: z.unknown().nullable().optional(),
  instance: z.string().nullable().optional(),
});
export type ProblemDetail = z.infer<typeof ProblemDetailSchema>;

// ── Cross-company lens (ADR 0007 layer 3) — mirrors app/schemas/lens.py ──

export const LensSummarySchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  description: z.string(),
  tickers: z.array(z.string()).default([]),
});
export type LensSummary = z.infer<typeof LensSummarySchema>;

export const LensPointSchema = z.object({
  year: z.number().int(),
  capex: z.number().nullable().default(null),
  revenue: z.number().nullable().default(null),
  ocf: z.number().nullable().default(null),
  capex_intensity: z.number().nullable().default(null),
  capex_to_ocf: z.number().nullable().default(null),
});
export type LensPoint = z.infer<typeof LensPointSchema>;

export const LensCompanySchema = z.object({
  ticker: z.string().min(1),
  name: z.string(),
  points: z.array(LensPointSchema),
});
export type LensCompany = z.infer<typeof LensCompanySchema>;

export const LensYearStatsSchema = z.object({
  year: z.number().int(),
  companies: z.number().int(),
  median: z.number(),
  p25: z.number(),
  p75: z.number(),
  low: z.number(),
  low_ticker: z.string(),
  high: z.number(),
  high_ticker: z.string(),
  total_capex: z.number(),
});
export type LensYearStats = z.infer<typeof LensYearStatsSchema>;

export const LensNarrativeSchema = z.object({
  headline: z.string().min(1),
  points: z.array(ThesisPointSchema).default([]),
});
export type LensNarrative = z.infer<typeof LensNarrativeSchema>;

export const LensReportSchema = LensSummarySchema.extend({
  method: z.string(),
  years: z.array(z.number().int()),
  companies: z.array(LensCompanySchema),
  stats: z.array(LensYearStatsSchema),
  facts: z.array(ClaimSchema).default([]),
  narrative: LensNarrativeSchema.nullable().default(null).catch(null),
  generated_at: z.string(),
});
export type LensReport = z.infer<typeof LensReportSchema>;
