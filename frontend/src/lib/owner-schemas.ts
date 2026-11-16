/**
 * Schemas for the owner's routes (``app/schemas/owner.py``). Only the lazy
 * owner pages import this. Positions carry tastytrade's live figures: they
 * live in memory only (never persisted) and never reach a prompt.
 */
import { z } from "zod";

import { ExpiryChainSchema } from "./options-schemas";

const MaybeNum = z.number().nullable().default(null);

export const OwnerStatusSchema = z.object({ tastytrade: z.boolean(), vault: z.boolean().default(false) });
export type OwnerStatus = z.infer<typeof OwnerStatusSchema>;

export const LiveQuoteSchema = z.object({
  bid: MaybeNum,
  ask: MaybeNum,
  mark: MaybeNum,
  /** A fraction: 0.48 is 48%. */
  iv: MaybeNum,
  /** Per share, as tastytrade gives them. */
  delta: MaybeNum,
  gamma: MaybeNum,
  theta: MaybeNum,
  vega: MaybeNum,
  updated_at: z.string().nullable().default(null),
});
export type LiveQuote = z.infer<typeof LiveQuoteSchema>;

export const PositionLegSchema = z.object({
  account: z.number(),
  kind: z.enum(["call", "put", "stock"]),
  symbol: z.string(),
  expiry: z.string().nullable().default(null),
  strike: MaybeNum,
  /** Signed: short is negative. */
  quantity: z.number(),
  multiplier: z.number(),
  average_open: MaybeNum,
  adjusted: z.boolean().default(false),
  /** When an option's expiry closes, from the server's calendar: 4 pm New
   * York, 1 pm on NYSE's half days. Null for stock. */
  expires_at: z.string().nullable().default(null),
  quote: LiveQuoteSchema.nullable().default(null),
});
export type PositionLeg = z.infer<typeof PositionLegSchema>;

export const PositionGroupSchema = z.object({
  underlying: z.string(),
  symbol: z.string(),
  quote: LiveQuoteSchema.nullable().default(null),
  expiries: z.array(z.string()).default([]),
  legs: z.array(PositionLegSchema),
});
export type PositionGroup = z.infer<typeof PositionGroupSchema>;

export const UnanalysedPositionSchema = z.object({
  account: z.number(),
  instrument_type: z.string(),
  symbol: z.string(),
  quantity: MaybeNum,
});

export const OwnerPositionsSchema = z.object({
  as_of: z.string(),
  // When tastytrade's marks were made: as_of in a session, else the last close.
  priced_at: z.string().nullable().default(null),
  accounts: z.number(),
  groups: z.array(PositionGroupSchema).default([]),
  unanalysed: z.array(UnanalysedPositionSchema).default([]),
  source: z.literal("tastytrade"),
  stale: z.boolean().default(false),
  truncated: z.boolean().default(false),
});
export type OwnerPositions = z.infer<typeof OwnerPositionsSchema>;

/** One of the owner's transactions from the encrypted copy. Money in is
 * positive, money out negative; fees are their total. */
export const OwnerTradeSchema = z.object({
  id: z.number(),
  account: z.number(),
  executed_at: z.string().nullable().default(null),
  date: z.string().nullable().default(null),
  type: z.string().nullable().default(null),
  sub_type: z.string().nullable().default(null),
  action: z.string().nullable().default(null),
  symbol: z.string().nullable().default(null),
  underlying: z.string().nullable().default(null),
  instrument_type: z.string().nullable().default(null),
  quantity: MaybeNum,
  price: MaybeNum,
  value: MaybeNum,
  fees: z.number().default(0),
  net_value: MaybeNum,
  description: z.string().nullable().default(null),
  order_id: MaybeNum,
  reverses_id: MaybeNum,
});
export type OwnerTrade = z.infer<typeof OwnerTradeSchema>;

const JournalLegSchema = z.object({
  symbol: z.string(),
  kind: z.enum(["call", "put", "stock"]),
  expiry: z.string().nullable().default(null),
  strike: MaybeNum,
  /** Signed: short is negative. */
  quantity: z.number(),
  closed: z.number().default(0),
});
export type JournalLeg = z.infer<typeof JournalLegSchema>;

const JournalPositionSchema = z.object({
  id: z.string(),
  account: z.number(),
  underlying: z.string(),
  structure: z.string(),
  legs: z.array(JournalLegSchema),
  opened_at: z.string().nullable().default(null),
  closed_at: z.string().nullable().default(null),
  /** The trading days (YYYY-MM-DD), shown in place of the UTC timestamps. */
  opened_on: z.string().nullable().default(null),
  closed_on: z.string().nullable().default(null),
  days_held: MaybeNum,
  status: z.enum(["open", "closed", "partly_closed"]),
  ended_by: z.enum(["closed", "expired", "assigned", "exercised", "mixed"]).nullable().default(null),
  origin: z.enum(["assignment", "exercise"]).nullable().default(null),
  origin_position: z.string().nullable().default(null),
  open_cash: MaybeNum,
  close_cash: MaybeNum,
  fees: z.number().default(0),
  /** On the closed part, fees in; null while open or when it can't be told. */
  realized: MaybeNum,
  rolled_from: z.string().nullable().default(null),
  rolled_to: z.string().nullable().default(null),
  note: z.string().nullable().default(null),
  transactions: z.array(z.number()).default([]),
});
export type JournalPosition = z.infer<typeof JournalPositionSchema>;

const EMPTY_TOTALS = { realized: 0, closed: 0, profitable: 0, partly: 0, unpriced: 0, average_days: null, fees: 0 };

const TradeJournalSchema = z.object({
  positions: z.array(JournalPositionSchema).default([]),
  months: z.array(z.object({ month: z.string(), realized: z.number() })).default([]),
  underlyings: z.array(z.object({ underlying: z.string(), realized: z.number() })).default([]),
  totals: z
    .object({
      realized: z.number().default(0),
      closed: z.number().default(0),
      profitable: z.number().default(0),
      /** Closed in part: their closed parts are in ``realized``. */
      partly: z.number().default(0),
      /** Closed without a computed P&L (after a split): counted apart. */
      unpriced: z.number().default(0),
      average_days: MaybeNum,
      fees: z.number().default(0),
    })
    .default(EMPTY_TOTALS),
  unmatched: z
    .array(z.object({ id: z.number(), date: z.string().nullable().default(null), symbol: z.string().nullable().default(null), reason: z.string() }))
    .default([]),
});
export type TradeJournal = z.infer<typeof TradeJournalSchema>;

export const OwnerTradesSchema = z.object({
  trades: z.array(OwnerTradeSchema).default([]),
  /** False when tastytrade couldn't be reached: the copy as it stood. */
  synced: z.boolean(),
  reason: z.string().nullable().default(null),
  /** The trades read as positions, computed by the server on each visit. */
  journal: TradeJournalSchema.default({ positions: [], months: [], underlyings: [], totals: EMPTY_TOTALS, unmatched: [] }),
});
export type OwnerTrades = z.infer<typeof OwnerTradesSchema>;

/** One expiry at tastytrade's live quotes, shaped like the delayed chain
 * (our own IVs from their mids). The owner's only; never persisted. */
export const LiveChainSchema = z.object({
  symbol: z.string(),
  expiry: z.string(),
  spot: z.number(),
  quoted_at: z.string(),
  updated_at: z.string().nullable().default(null),
  chain: ExpiryChainSchema,
  source: z.literal("tastytrade"),
});
export type LiveChain = z.infer<typeof LiveChainSchema>;


// The owner's IV history from tastytrade (/v1/owner/options/{symbol}/history).
// Every figure is a fraction (0.41 = 41%), range-checked on the server.
export const IvPointSchema = z.object({
  date: z.string(),
  close: MaybeNum,
  iv: MaybeNum,
  rv20: MaybeNum,
});
export type IvPoint = z.infer<typeof IvPointSchema>;

export const IvHistorySchema = z.object({
  symbol: z.string(),
  as_of: z.string(),
  metrics: z.object({
    iv_index: MaybeNum,
    iv30: MaybeNum,
    iv_rank: MaybeNum,
    iv_percentile: MaybeNum,
    hv30: MaybeNum,
    hv60: MaybeNum,
    hv90: MaybeNum,
    updated_at: z.string().nullable().default(null),
  }),
  points: z.array(IvPointSchema).default([]),
  year: z.object({
    sessions: z.number().default(0),
    iv_low: MaybeNum,
    iv_high: MaybeNum,
    iv_median: MaybeNum,
    iv_rank: MaybeNum,
    iv_percentile: MaybeNum,
  }),
  iv_since: z.string().nullable().default(null),
  complete: z.boolean().default(true),
  source: z.literal("tastytrade"),
});
export type IvHistory = z.infer<typeof IvHistorySchema>;
