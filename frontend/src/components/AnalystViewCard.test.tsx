import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { AnalystViewCard } from "./AnalystViewCard";
import type { Claim, ResearchReport, Thesis } from "../lib/schemas";

const SRC = { tool: "computed.analytics", fetched_at: "2026-11-08T14:00:00+00:00" };

function claim(description: string, value: number, unit: Claim["unit"]): Claim {
  return { description, value, unit, source: SRC, history: [] };
}

const THESIS: Thesis = {
  headline: "A durable franchise priced for durability.",
  bull: [
    {
      text: "Operating margin widened 1.16 pts.",
      claim_refs: [
        { section: "Quality", index: 1 },
        { section: "Quality", index: 9 }, // gone from the report: no chip
      ],
    },
  ],
  bear: [{ text: "A 35.51% premium to peers.", claim_refs: [{ section: "Peers", index: 0 }] }],
  changed: [],
  watch: [{ text: "Cash conversion at 0.98.", claim_refs: [{ section: "Quality", index: 0 }] }],
};

function report(thesis: Thesis | null): ResearchReport {
  return {
    symbol: "KO",
    generated_at: "2026-11-08T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    name: "The Coca-Cola Company",
    sector: "consumer_staples",
    layout_signals: {
      is_unprofitable_ttm: false,
      beat_rate_below_30pct: false,
      cash_runway_quarters: null,
      gross_margin_negative: false,
      debt_rising_cash_falling: false,
    },
    sections: [
      {
        title: "Quality",
        summary: "",
        confidence: "high",
        card_narrative: null,
        claims: [
          claim("Free cash flow ÷ net income (trailing 12 months)", 0.98, "ratio"),
          claim("Operating margin change, 2025-Q3 → 2026-Q3", 0.0116, "percentage_points"),
        ],
      },
      {
        title: "Peers",
        summary: "",
        confidence: "high",
        card_narrative: null,
        claims: [claim("Median trailing P/E", 20.83, "ratio")],
      },
    ],
    thesis,
  };
}

describe("AnalystViewCard", () => {
  it("leads with the headline and lists the cases that have points", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    expect(screen.getByText("A durable franchise priced for durability.")).toBeInTheDocument();
    const lists = screen.getAllByTestId("analyst-view-list").map((l) => l.getAttribute("data-list"));
    expect(lists).toEqual(["Bull case", "Bear case", "What to watch"]); // empty "What changed" hidden
  });

  it("shows each point's evidence as value + claim chips, skipping refs that don't resolve", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    const bull = screen.getAllByTestId("analyst-view-list")[0];
    const chips = within(bull).getAllByTestId("evidence-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent("+1.16 pts");
    expect(chips[0]).toHaveTextContent("Operating margin change, 2025-Q3 → 2026-Q3");
  });

  it("scrolls to the card that shows the cited claim", () => {
    const target = document.createElement("div");
    target.setAttribute("data-section-anchor", "Valuation"); // Peers live in the Valuation card
    target.scrollIntoView = vi.fn();
    document.body.appendChild(target);
    render(<AnalystViewCard report={report(THESIS)} />);
    fireEvent.click(screen.getByRole("button", { name: /Median trailing P\/E: 20.83/ }));
    expect(target.scrollIntoView).toHaveBeenCalled();
    target.remove();
  });

  it("asks for a regenerate when the report predates the analyst view", () => {
    render(<AnalystViewCard report={report(null)} />);
    expect(screen.getByTestId("analyst-view-missing")).toHaveTextContent(/Regenerate/);
    expect(screen.queryByTestId("analyst-view")).toBeNull();
  });
});
