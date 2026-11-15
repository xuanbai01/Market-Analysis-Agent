import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Analysis } from "../../lib/options-strategy";
import { PayoffChart } from "./PayoffChart";

const flat: Analysis = {
  cost: 0,
  breakevens: [],
  maxProfit: 0,
  maxLoss: 0,
  pop: 0,
  priced: [
    { kind: "call", side: 1, strike: 100, premium: 1 },
    { kind: "call", side: -1, strike: 100, premium: 1 },
  ],
};

describe("PayoffChart", () => {
  it("draws a payoff of zero everywhere on a sane scale", () => {
    render(<PayoffChart mid={flat} natural={flat} forward={100} sigma={0.1} />);
    for (const id of ["strategy-payoff-mid", "strategy-payoff-natural"]) {
      expect(screen.getByTestId(id).getAttribute("d")).not.toMatch(/NaN/);
    }
  });
});
