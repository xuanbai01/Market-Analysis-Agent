import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CitedPoints } from "./CitedPoints";

const source = { tool: "computed.options", fetched_at: "2026-11-15T05:37:50Z", url: null, detail: null };

describe("CitedPoints", () => {
  it("shows each cited fact's value, a number or a reason", () => {
    render(
      <CitedPoints
        evidenceTestId="evidence"
        points={[
          { text: "IV30 is 59.46%; no earnings move is priced.", title: null, claim_refs: [{ section: "Options", index: 0 }, { section: "Options", index: 1 }] },
        ]}
        facts={[
          { description: "Implied volatility, 30 days (IV30)", value: 0.5946, unit: "fraction", source, history: [] },
          { description: "Implied earnings move: not priced", value: "the first expiry after the report is 98 days out", unit: "string", source, history: [] },
        ]}
      />,
    );
    const chips = screen.getAllByTestId("evidence");
    expect(chips[0]).toHaveTextContent("59.46%");
    expect(chips[1]).toHaveTextContent("98 days out");
  });

  it("skips a reference to a fact that isn't there", () => {
    render(<CitedPoints evidenceTestId="evidence" points={[{ text: "x", title: null, claim_refs: [{ section: "Options", index: 5 }] }]} facts={[]} />);
    expect(screen.queryByTestId("evidence")).toBeNull();
  });
});
