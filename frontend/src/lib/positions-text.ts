/**
 * The positions page's sentences, written in code from the figures (no
 * prompt: the owner's positions never reach one, ADR 0009). Each says what
 * a number is and where it comes from; none reads a direction into it or
 * says what to do.
 */
import type { EarningsBlock } from "./options-schemas";
import { type Sentence, dateLabel, strikeLabel } from "./options-text";
import type { PositionGroup, PositionLeg } from "./owner-schemas";
import type { Greeks, Scenario } from "./positions-math";

const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;

/** "+$1,320", "−$820", "$0". */
export function signedUsd(v: number): string {
  const rounded = Math.round(v);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
  return `${sign}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

/** "$32,140". */
export function usd(v: number): string {
  return `${v < 0 ? "−" : ""}$${Math.abs(Math.round(v)).toLocaleString("en-US")}`;
}

function count(v: number): string {
  return Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** "2 short Dec 18 $200 calls", "1 long Jan 15 $650 put", "200 shares", "50 shares short". */
export function legLabel(leg: Pick<PositionLeg, "kind" | "quantity" | "expiry" | "strike"> & { adjusted?: boolean }): string {
  const n = Math.abs(leg.quantity);
  if (leg.kind === "stock") return `${count(n)} share${n === 1 ? "" : "s"}${leg.quantity < 0 ? " short" : ""}`;
  const side = leg.quantity < 0 ? "short" : "long";
  const contract = `${leg.expiry ? dateLabel(leg.expiry) : "?"} ${leg.strike === null ? "?" : strikeLabel(leg.strike)} ${leg.kind}${n === 1 ? "" : "s"}`;
  return `${count(n)} ${side} ${contract}${leg.adjusted ? " (adjusted)" : ""}`;
}

function listed(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** What's held, what it's worth at the marks, and the P&L since it was opened. */
export function groupSentence(group: PositionGroup, value: number | null, cost: number | null): Sentence {
  const parts: Sentence = [`${group.underlying}: ${listed(group.legs.map(legLabel))}.`];
  if (value !== null) {
    parts.push(" Worth ", { strong: usd(value) }, " at tastytrade's marks");
    if (cost !== null) parts.push(", ", { strong: signedUsd(value - cost) }, " since it was opened");
    parts.push(".");
  }
  return parts;
}

/** The Greeks as P&L: per 1% move, per day, per IV point. */
export function greeksSentence(g: Greeks): Sentence | null {
  if (g.deltaShares === null || g.deltaDollars === null) return null;
  const shares = Math.round(g.deltaShares); // signed after rounding: no "−0"
  const parts: Sentence = [
    "Moves like ",
    { strong: `${shares < 0 ? "−" : ""}${count(shares)} shares` },
    ": ",
    { strong: signedUsd(g.deltaDollars) },
    " for a 1% rise",
  ];
  const gamma = g.gammaShares === null ? 0 : Math.round(g.gammaShares);
  if (gamma !== 0) {
    parts.push(", which itself changes by ", { strong: `${gamma < 0 ? "−" : "+"}${count(gamma)} shares` }, " per 1%");
  }
  parts.push(".");
  if (g.thetaDay !== null) parts.push(" A day passing: ", { strong: signedUsd(g.thetaDay) }, ".");
  if (g.vegaPoint !== null) parts.push(" IV one point higher: ", { strong: signedUsd(g.vegaPoint) }, ".");
  return parts;
}

/** The what-if, in words. */
export function scenarioSentence(symbol: string, scenario: Scenario, price: number, pnl: number | null): Sentence {
  if (pnl === null) return ["This position can't be valued before expiry: a leg has no IV from tastytrade, or isn't modelled."];
  const changes: Sentence = [];
  if (scenario.move !== 0) {
    changes.push(`${symbol} `, { strong: `${pct(Math.abs(scenario.move), 0)} ${scenario.move > 0 ? "higher" : "lower"} (${strikeLabel(Math.round(price * 100) / 100)})` });
  }
  if (scenario.ivShift !== 0) {
    if (changes.length) changes.push(", ");
    changes.push("IV ", { strong: `${Math.round(Math.abs(scenario.ivShift) * 100)} points ${scenario.ivShift > 0 ? "higher" : "lower"}` });
  }
  if (scenario.days !== 0) {
    if (changes.length) changes.push(" ");
    changes.push(changes.length ? "in " : "In ", { strong: `${scenario.days} day${scenario.days === 1 ? "" : "s"}` });
  }
  if (changes.length === 0) return ["At today's price and IVs, the model puts the P&L at ", { strong: signedUsd(pnl) }, "."];
  const lead: Sentence = scenario.move !== 0 || scenario.ivShift !== 0 ? ["With ", ...changes] : changes;
  return [...lead, ", the P&L would be ", { strong: signedUsd(pnl) }, "."];
}

/** The risk-neutral chance of profit, labelled for what it is. */
export function marketSentence(chance: number | null, expiry: string | null, spread: boolean): Sentence | null {
  if (spread) return ["Option prices imply no single chance of profit for a spread across expiries."];
  if (chance === null || expiry === null) return null;
  return [
    "Option prices put the chance this is in profit at ",
    { strong: dateLabel(expiry) },
    "'s close at ",
    { strong: pct(chance, 0) },
    ": what the market implies, not a forecast.",
  ];
}

/** How often history's moves would have paid, labelled for what it is. */
/** "5 years", "1 year", "7 months". */
function span(years: number): string {
  if (years >= 1) {
    const n = Math.round(years);
    return `${n} year${n === 1 ? "" : "s"}`;
  }
  const months = Math.max(1, Math.round(years * 12));
  return `${months} month${months === 1 ? "" : "s"}`;
}

export function historySentence(
  symbol: string,
  result: { share: number; windows: number; years: number } | null,
  sessions: number,
): Sentence | null {
  if (result === null) return null;
  return [
    `Over the last ${span(result.years)}, ${symbol}'s moves across ${sessions} session${sessions === 1 ? "" : "s"} would have left it in profit `,
    { strong: pct(result.share, 0) },
    ` of the time (${result.windows.toLocaleString("en-US")} windows): past moves, not a forecast.`,
  ];
}

/** The next report, when it falls before the position's first expiry. */
export function earningsSentence(symbol: string, earnings: EarningsBlock | null, firstExpiry: string | null): Sentence | null {
  // The first session that trades on it: a report after the expiry day's close comes too late.
  const reacts = earnings?.reaction_date ?? earnings?.next_date;
  if (!earnings?.next_date || !reacts || firstExpiry === null || reacts > firstExpiry) return null;
  const parts: Sentence = [`${symbol} reports on `, { strong: dateLabel(earnings.next_date) }, ", before this position's first expiry"];
  if (earnings.implied_move !== null) parts.push(": options imply a ", { strong: `±${pct(earnings.implied_move)}` }, " move for it");
  else if (earnings.refused) parts.push(` (no implied move: ${earnings.refused})`);
  if (earnings.past_mean_abs !== null && earnings.past.length > 0) {
    parts.push(`; the last ${earnings.past.length} moved `, { strong: pct(earnings.past_mean_abs) }, " on average");
  }
  parts.push(".");
  return parts;
}
