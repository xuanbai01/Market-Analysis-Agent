/**
 * Zod schemas for the options page (ADR 0008), mirroring
 * app/schemas/options.py. Imported only by the lazy options page, so they
 * stay out of the main chunk. Unknown fields are ignored; an unknown
 * timing reads as "unknown".
 */
import { z } from "zod";

import { ClaimSchema, ThesisPointSchema } from "./schemas";

const Num = z.number();
const MaybeNum = z.number().nullable();

export const TimingSchema = z.enum(["before_open", "during", "after_close", "unknown"]).catch("unknown");
export type Timing = z.infer<typeof TimingSchema>;

export const ExpirySummarySchema = z.object({
  expiry: z.string(),
  days: Num,
  sessions: Num,
  forward: Num,
  forward_from_parity: z.boolean(),
  atm_iv: Num,
  expected_move: Num,
  low: Num,
  high: Num,
  straddle: MaybeNum.default(null),
  straddle_strike: MaybeNum.default(null),
  call_open_interest: Num,
  put_open_interest: Num,
  call_volume: Num,
  put_volume: Num,
  includes_earnings: z.boolean().default(false),
});
export type ExpirySummary = z.infer<typeof ExpirySummarySchema>;

export const SmilePointSchema = z.object({
  strike: Num,
  log_moneyness: Num,
  iv: Num,
  side: z.enum(["put", "call"]),
});
export type SmilePoint = z.infer<typeof SmilePointSchema>;

export const ChainRowSchema = z.object({
  strike: Num,
  call_bid: Num,
  call_ask: Num,
  call_iv: MaybeNum,
  call_delta: MaybeNum,
  call_open_interest: Num,
  call_volume: Num,
  call_usable: z.boolean(),
  put_bid: Num,
  put_ask: Num,
  put_iv: MaybeNum,
  put_delta: MaybeNum,
  put_open_interest: Num,
  put_volume: Num,
  put_usable: z.boolean(),
});
export type ChainRow = z.infer<typeof ChainRowSchema>;

export const OpenInterestPointSchema = z.object({ strike: Num, call: Num, put: Num });
export type OpenInterestPoint = z.infer<typeof OpenInterestPointSchema>;

export const ExpiryChainSchema = z.object({
  expiry: z.string(),
  days: Num,
  forward: Num,
  atm_iv: MaybeNum,
  smile: z.array(SmilePointSchema).default([]),
  rows: z.array(ChainRowSchema).default([]),
  open_interest: z.array(OpenInterestPointSchema).default([]),
});
export type ExpiryChain = z.infer<typeof ExpiryChainSchema>;

export const PastMoveSchema = z.object({
  announced: z.string(),
  timing: TimingSchema,
  move: Num,
  spans_extra_day: z.boolean().default(false),
});
export type PastMove = z.infer<typeof PastMoveSchema>;

export const EarningsBlockSchema = z.object({
  next_date: z.string().nullable(),
  next_timing: TimingSchema.nullable(),
  estimated: z.boolean().default(false),
  reaction_date: z.string().nullable(),
  implied_move: MaybeNum,
  implied_move_usd: MaybeNum,
  event_sigma: MaybeNum,
  base_vol: MaybeNum,
  method: z.string().nullable(),
  refused: z.string().nullable(),
  expiries: z.array(z.string()).default([]),
  past: z.array(PastMoveSchema).default([]),
  past_mean_abs: MaybeNum,
});
export type EarningsBlock = z.infer<typeof EarningsBlockSchema>;

export const IvHistorySchema = z.object({
  points: z.array(z.object({ date: z.string(), iv30: Num })).default([]),
  sessions: Num,
  since: z.string().nullable(),
  percentile: MaybeNum,
  rank: MaybeNum,
});
export type IvHistory = z.infer<typeof IvHistorySchema>;

export const OptionsReportSchema = z.object({
  symbol: z.string(),
  name: z.string().nullable().default(null),
  status: z.enum(["ok", "no_options", "no_usable_quotes"]),
  spot: MaybeNum,
  quoted_at: z.string(),
  // The server says whether these are the close's quotes; one that
  // predates the field is read as a delayed print.
  at_close: z.boolean().default(false),
  rate: Num,
  rate_assumed: z.boolean(),
  iv30: MaybeNum,
  iv30_extrapolated: z.boolean().default(false),
  iv90: MaybeNum,
  skew25: MaybeNum,
  rv20: MaybeNum,
  rv60: MaybeNum,
  put_call_open_interest: MaybeNum,
  put_call_volume: MaybeNum,
  expiries: z.array(ExpirySummarySchema).default([]),
  listed_expiries: z.array(z.string()).default([]),
  chain: ExpiryChainSchema.nullable(),
  earnings: EarningsBlockSchema.nullable(),
  history: IvHistorySchema,
  claims: z.array(ClaimSchema).default([]),
  generated_at: z.string(),
});
export type OptionsReport = z.infer<typeof OptionsReportSchema>;

/** The cited read (GET /v1/options/{symbol}/read): points cite ``claims``
 * by index, the report's claims as they stood when it was written. */
export const OptionsReadSchema = z.object({
  symbol: z.string(),
  quoted_at: z.string(),
  at_close: z.boolean().default(false),
  headline: z.string(),
  points: z.array(ThesisPointSchema).default([]),
  claims: z.array(ClaimSchema).default([]),
  generated_at: z.string(),
});
export type OptionsRead = z.infer<typeof OptionsReadSchema>;
