/**
 * What each options chart needs to draw anything. A chart with less returns
 * null, and the page leaves out its panel by the same check, so no titled
 * panel stands empty.
 */
import type { EarningsBlock, ExpirySummary } from "../../lib/options-schemas";

/** The cone runs out to about six months. */
export const CONE_MAX_DAYS = 200;

export function conePoints(expiries: ExpirySummary[]): ExpirySummary[] {
  return expiries.filter((e) => e.days <= CONE_MAX_DAYS).sort((a, b) => a.days - b.days);
}

export const drawsCone = (expiries: ExpirySummary[]) => conePoints(expiries).length >= 2;

export const drawsTerm = (expiries: ExpirySummary[]) => expiries.length >= 2;

export const drawsEarnings = (e: EarningsBlock) => e.past.length > 0 || e.implied_move !== null || e.next_date !== null;
