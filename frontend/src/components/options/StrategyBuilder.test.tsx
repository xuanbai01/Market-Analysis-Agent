import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExpiryChainSchema } from "../../lib/options-schemas";
import { RAW_OPTIONS_REPORT } from "./fixture";
import { StrategyBuilder } from "./StrategyBuilder";

const CHAIN = ExpiryChainSchema.parse(RAW_OPTIONS_REPORT.chain);

const summary = () => screen.getByTestId("strategy-summary");
const row = (label: string) => within(summary()).getByText(label).closest("tr")!;

describe("StrategyBuilder", () => {
  it("starts on a long call at the money, with an unlimited upside", () => {
    render(<StrategyBuilder chain={CHAIN} />);
    expect(screen.getByRole("button", { name: "Long call" })).toHaveAttribute("aria-pressed", "true");
    const legs = screen.getAllByTestId("strategy-leg");
    expect(legs).toHaveLength(1);
    expect(within(legs[0]).getByTestId("strategy-leg-strike")).toHaveValue("165");
    expect(row("Max profit")).toHaveTextContent("Unlimited");
    expect(row("Net")).toHaveTextContent(/Debit \$/);
    expect(row("Probability of profit")).toHaveTextContent(/\d+%/);
    expect(screen.getByTestId("strategy-payoff-mid")).toBeInTheDocument();
    expect(screen.getByTestId("strategy-payoff-natural")).toBeInTheDocument();
  });

  it("builds an iron condor: four legs, a credit, two breakevens", () => {
    render(<StrategyBuilder chain={CHAIN} />);
    fireEvent.click(screen.getByRole("button", { name: "Iron condor" }));
    expect(screen.getAllByTestId("strategy-leg")).toHaveLength(4);
    expect(row("Net")).toHaveTextContent(/Credit \$/);
    expect(within(row("Breakevens")).getAllByText(/\$\d/).length).toBeGreaterThanOrEqual(2);
    expect(row("Max loss")).not.toHaveTextContent("Unlimited");
  });

  it("re-prices when a strike changes", () => {
    render(<StrategyBuilder chain={CHAIN} />);
    const before = row("Breakevens").textContent;
    fireEvent.change(screen.getByTestId("strategy-leg-strike"), { target: { value: "175" } });
    expect(row("Breakevens").textContent).not.toBe(before);
  });

  it("says when a leg can't be bought at the natural price", () => {
    const rows = CHAIN.rows.map((r) => (r.strike === 165 ? { ...r, call_ask: 0 } : r));
    render(<StrategyBuilder chain={{ ...CHAIN, rows }} />);
    // Strike 165 has no offer now, so the template moves to the nearest that has one.
    expect(screen.getByTestId("strategy-leg-strike")).not.toHaveValue("165");
    fireEvent.change(screen.getByTestId("strategy-leg-strike"), { target: { value: "165" } });
    expect(screen.getByTestId("strategy-unpriced")).toHaveTextContent(/no offer/i);
  });

  it("gives no probability without a smile, and says why", () => {
    render(<StrategyBuilder chain={{ ...CHAIN, smile: [] }} />);
    expect(row("Probability of profit")).toHaveTextContent("—");
    expect(screen.getByTestId("strategy-no-smile")).toHaveTextContent(/no smile/i);
  });

  it("signs the best and worst case, so a position that loses everywhere says so", () => {
    // 165 call at 10 against a 170 call at 2: a cost of 8 on a 5-point spread.
    const rows = CHAIN.rows.map((r) =>
      r.strike === 165 ? { ...r, call_bid: 10, call_ask: 10 } : r.strike === 170 ? { ...r, call_bid: 2, call_ask: 2 } : r,
    );
    render(<StrategyBuilder chain={{ ...CHAIN, rows }} />);
    fireEvent.click(screen.getByRole("button", { name: "Bull call spread" }));
    fireEvent.change(screen.getAllByTestId("strategy-leg-strike")[1], { target: { value: "170" } });
    expect(row("Max profit")).toHaveTextContent("−$300.00");
    expect(row("Max loss")).toHaveTextContent("−$800.00");
  });

  it("still prices at the natural price a leg that can only be sold", () => {
    // The short put has a bid but no offer: no mid, but it can be sold at the bid.
    const rows = CHAIN.rows.map((r) => (r.strike === 150 ? { ...r, put_ask: 0 } : r));
    render(<StrategyBuilder chain={{ ...CHAIN, rows }} />);
    fireEvent.click(screen.getByRole("button", { name: "Bull put spread" }));
    fireEvent.change(screen.getAllByTestId("strategy-leg-strike")[0], { target: { value: "150" } });
    expect(screen.getByTestId("strategy-unpriced")).toHaveTextContent(/no mid/i);
    expect(row("Net")).toHaveTextContent(/Credit \$/);
    expect(screen.getByTestId("strategy-payoff-natural")).toBeInTheDocument();
    expect(screen.queryByTestId("strategy-payoff-mid")).toBeNull();
  });

  it("says why there's no probability on an expiry with no time left", () => {
    render(<StrategyBuilder chain={{ ...CHAIN, days: 0 }} />);
    expect(screen.getByTestId("strategy-no-smile")).toHaveTextContent(/no time left/i);
  });

  it("names a leg with no bid as having no mid", () => {
    const rows = CHAIN.rows.map((r) => (r.strike === 165 ? { ...r, call_bid: 0 } : r));
    render(<StrategyBuilder chain={{ ...CHAIN, rows }} />);
    fireEvent.change(screen.getByTestId("strategy-leg-strike"), { target: { value: "165" } });
    expect(screen.getByTestId("strategy-unpriced")).toHaveTextContent(/no bid/i);
    expect(row("Net")).toHaveTextContent(/Debit \$/); // still bought at the offer
  });

  it("shows the leg's quote by the same rule it is priced by", () => {
    const rows = CHAIN.rows.map((r) => (r.strike === 165 ? { ...r, call_bid: 0, call_ask: 0.4 } : r));
    render(<StrategyBuilder chain={{ ...CHAIN, rows }} />);
    fireEvent.change(screen.getByTestId("strategy-leg-strike"), { target: { value: "165" } });
    const cells = within(screen.getByTestId("strategy-leg")).getAllByRole("cell");
    expect(cells.map((c) => c.textContent).slice(2, 5)).toEqual(["0.00", "0.40", "—"]); // bid, ask, no mid
  });

  it("draws a payoff that is zero everywhere without breaking the scale", () => {
    render(<StrategyBuilder chain={CHAIN} />);
    fireEvent.click(screen.getByRole("button", { name: "Bull call spread" }));
    fireEvent.change(screen.getAllByTestId("strategy-leg-strike")[1], { target: { value: "165" } });
    expect(screen.getByTestId("strategy-payoff-mid").getAttribute("d")).not.toMatch(/NaN/);
  });

  it("draws no one-sigma band without an IV", () => {
    render(<StrategyBuilder chain={{ ...CHAIN, atm_iv: null, smile: [] }} />);
    expect(screen.queryByTestId("strategy-payoff-band")).toBeNull();
    expect(screen.getByTestId("strategy-payoff-mid")).toBeInTheDocument();
  });

  it("says when the chain can't fit a template", () => {
    const rows = CHAIN.rows.map((r) => ({ ...r, put_ask: 0, put_bid: 0 }));
    render(<StrategyBuilder chain={{ ...CHAIN, rows }} />);
    fireEvent.click(screen.getByRole("button", { name: "Bull put spread" }));
    expect(screen.getByTestId("strategy-unavailable")).toHaveTextContent(/not enough quoted strikes/i);
    expect(screen.queryByTestId("strategy-summary")).toBeNull();
  });

  it("shows the profit or loss at a price on hover", () => {
    render(<StrategyBuilder chain={CHAIN} />);
    const hits = screen.getAllByTestId("strategy-payoff-hit");
    fireEvent.mouseEnter(hits[hits.length - 1]);
    expect(screen.getByTestId("strategy-payoff-tooltip")).toHaveTextContent(/at mid/i);
  });

  it("states what the probability is and isn't, and that templates aren't advice", () => {
    render(<StrategyBuilder chain={CHAIN} />);
    const note = screen.getByTestId("strategy-disclaimer");
    expect(note).toHaveTextContent(/risk-neutral/i);
    expect(note).toHaveTextContent(/at expiry/i);
    expect(note).toHaveTextContent(/not a recommendation/i);
    expect(note).toHaveTextContent(/assigned early/i);
  });
});
