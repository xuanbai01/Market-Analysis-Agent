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
});
export type OwnerTrade = z.infer<typeof OwnerTradeSchema>;

export const OwnerTradesSchema = z.object({
  trades: z.array(OwnerTradeSchema).default([]),
  /** False when tastytrade couldn't be reached: the copy as it stood. */
  synced: z.boolean(),
  reason: z.string().nullable().default(null),
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

