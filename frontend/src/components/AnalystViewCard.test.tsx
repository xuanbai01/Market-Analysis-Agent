import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { AnalystViewCard } from "./AnalystViewCard";
import { ThesisSchema, type Claim, type ResearchReport, type Thesis } from "../lib/schemas";

const SRC = { tool: "computed.analytics", fetched_at: "2026-11-08T14:00:00+00:00" };

function claim(description: string, value: number, unit: Claim["unit"]): Claim {
  return { description, value, unit, source: SRC, history: [] };
}

const THESIS: Thesis = {
  headline: "A durable franchise priced for durability.",
  bull: [
    {
      title: "Margins still expanding",
      text: "Operating margin widened 1.16 pts year over year.",
      claim_refs: [
        { section: "Quality", index: 1 },
        { section: "Quality", index: 9 }, // gone from the report: left out
      ],
    },
  ],
  bear: [
    {
      title: "Rich valuation vs peers",
      text: "A 35.51% premium to the peer median P/E of 20.83.",
      claim_refs: [{ section: "Peers", index: 0 }],
    },
  ],
  changed: [],
  watch: [
    // A point without a title (older report, or a title dropped in code).
    { title: null, text: "Cash conversion at 0.98 times net income.", claim_refs: [{ section: "Quality", index: 0 }] },
  ],
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

function pointRow(title: string): HTMLElement {
  return screen.getByRole("button", { name: new RegExp(title) });
}

describe("AnalystViewCard", () => {
  it("leads with the headline and lists the cases that have points", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    expect(screen.getByText("A durable franchise priced for durability.")).toBeInTheDocument();
    const lists = screen.getAllByTestId("analyst-view-list").map((l) => l.getAttribute("data-list"));
    expect(lists).toEqual(["Bull case", "Bear case", "What to watch"]); // empty "What changed" hidden
  });

  // 2026-11 redesign: the card was 982 px of 40-word sentences and 34
  // chips. By default each point is now one line: its title and the
  // value of its first cited claim.
  it("lists each point as its title and key figure, details closed", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    const row = pointRow("Margins still expanding");
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(within(row).getByTestId("key-figure")).toHaveTextContent("+1.16 pts");
    expect(screen.queryByText("Operating margin widened 1.16 pts year over year.")).toBeNull();
    expect(screen.queryAllByTestId("evidence-row")).toHaveLength(0);
  });

  // Live KO showed "Unbroken beat streak 11.78%" — the model cited EPS
  // growth first — so each figure now names the claim it comes from.
  it("names the claim each key figure comes from", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    const row = pointRow("Margins still expanding");
    expect(within(row).getByTestId("key-figure-label")).toHaveTextContent("Operating margin change");
    expect(within(pointRow("Rich valuation vs peers")).getByTestId("key-figure-label")).toHaveTextContent(
      "Median trailing P/E",
    );
  });

  it("opens a point to its full text and evidence, skipping refs that don't resolve", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    const row = pointRow("Margins still expanding");
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Operating margin widened 1.16 pts year over year.")).toBeInTheDocument();
    const evidence = screen.getAllByTestId("evidence-row");
    expect(evidence).toHaveLength(1);
    expect(evidence[0]).toHaveTextContent("Operating margin change, 2025-Q3 → 2026-Q3");
    expect(evidence[0]).toHaveTextContent("+1.16 pts");
  });

  it("uses a point's text as its label when it has no title", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    const row = pointRow("Cash conversion at 0.98");
    expect(within(row).getByTestId("key-figure")).toHaveTextContent("0.98");
  });

  it("scrolls to the card that shows the cited claim", () => {
    const target = document.createElement("div");
    target.setAttribute("data-section-anchor", "Valuation"); // Peers live in the Valuation card
    target.scrollIntoView = vi.fn();
    document.body.appendChild(target);
    render(<AnalystViewCard report={report(THESIS)} />);
    fireEvent.click(pointRow("Rich valuation vs peers"));
    fireEvent.click(screen.getByRole("button", { name: /Median trailing P\/E: 20.83/ }));
    expect(target.scrollIntoView).toHaveBeenCalled();
    target.remove();
  });

  it("opens and closes every point at once", () => {
    render(<AnalystViewCard report={report(THESIS)} />);
    fireEvent.click(screen.getByRole("button", { name: /show all details/i }));
    expect(screen.getAllByTestId("evidence-row")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: /hide details/i }));
    expect(screen.queryAllByTestId("evidence-row")).toHaveLength(0);
  });

  it("asks for a regenerate when the report predates the analyst view", () => {
    render(<AnalystViewCard report={report(null)} />);
    expect(screen.getByTestId("analyst-view-missing")).toHaveTextContent(/Regenerate/);
    expect(screen.queryByTestId("analyst-view")).toBeNull();
  });

  it("reads cached points without a title", () => {
    const parsed = ThesisSchema.parse({
      headline: "Old report.",
      bull: [{ text: "Margins widened.", claim_refs: [{ section: "Quality", index: 0 }] }],
    });
    expect(parsed.bull[0].title).toBeNull();
  });
});
