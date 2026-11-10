import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { CompareRiskDiff } from "./CompareRiskDiff";
import type { Claim, ClaimValue, ResearchReport } from "../../lib/schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "sec.ten_k_risks_diff", fetched_at: "2026-11-08T14:00:00+00:00" },
    history: [],
  };
}

function report(symbol: string, topics: [string, number][]): ResearchReport {
  return {
    symbol,
    generated_at: "2026-11-08T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    sections: [
      {
        title: "Risk Factors",
        summary: "",
        confidence: "high",
        claims: [
          claim("Newly added risk paragraphs vs prior 10-K", 12),
          claim("Risk paragraphs dropped vs prior 10-K", 3),
          claim("Risk paragraphs kept (carryover)", 200),
          claim("Item 1A char delta vs prior 10-K", 4000),
          ...topics.map(([label, delta]) => claim(`${label} risk paragraph delta vs prior 10-K`, delta)),
        ],
      },
    ],
  } as unknown as ResearchReport;
}

describe("CompareRiskDiff", () => {
  it("puts both tickers on one scale, so equal bars mean equal changes", () => {
    const { container } = render(
      <CompareRiskDiff a={report("KO", [["IP", 1]])} b={report("NVDA", [["Export controls", 10]])} />,
    );
    const ko = container.querySelector("[data-side-risk='a'] .bg-strata-neg") as HTMLElement;
    const nvda = container.querySelector("[data-side-risk='b'] .bg-strata-neg") as HTMLElement;
    // Shared scale = 10 (NVDA's largest): KO's +1 is a tenth of the track.
    expect(nvda.style.width).toBe("100%");
    expect(ko.style.width).toBe("10%");
  });

  it("returns null when neither side has a risk diff", () => {
    const empty = { symbol: "X", sections: [] } as unknown as ResearchReport;
    const { container } = render(<CompareRiskDiff a={empty} b={empty} />);
    expect(container.firstChild).toBeNull();
  });
});
