import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OptionsReportSchema, type OpenInterestTotal } from "../../lib/options-schemas";
import { compactCount, openInterestHistorySentence, type Sentence } from "../../lib/options-text";
import { RAW_OPTIONS_REPORT } from "./fixture";
import { OpenInterestHistory } from "./OpenInterestHistory";

const text = (s: Sentence | null) => (s === null ? null : s.map((p) => (typeof p === "string" ? p : `**${p.strong}**`)).join(""));

const TWO: OpenInterestTotal[] = [
  { date: "2026-11-16", call: 9_270_000, put: 8_780_000, expiries: 24, listed: 24 },
  { date: "2026-11-17", call: 10_240_000, put: 9_020_000, expiries: 24, listed: 24 },
];

describe("open interest history words", () => {
  it("counts contracts in short form", () => {
    expect(compactCount(10_240_000)).toBe("10.24M");
    expect(compactCount(950_400)).toBe("950K");
    expect(compactCount(820)).toBe("820");
    expect(compactCount(999_600)).toBe("1.00M"); // not "1000K"
  });

  it("gives the latest totals and the change since the first session", () => {
    expect(text(openInterestHistorySentence(TWO))).toBe(
      "Across all 24 expiries: **10.24M calls** and **9.02M puts** open on Nov 17 (put/call **0.88**); calls **up 10.5%** and puts **up 2.7%** since Nov 16.",
    );
  });

  it("with one session, says when recording began", () => {
    expect(text(openInterestHistorySentence(TWO.slice(0, 1)))).toBe(
      "Across all 24 expiries: **9.27M calls** and **8.78M puts** open on Nov 16 (put/call **0.95**). Recorded daily from Nov 16.",
    );
  });

  it("says when some expiries weren't read", () => {
    const partial = [{ ...TWO[1], expiries: 23 }];
    expect(text(openInterestHistorySentence(partial))).toMatch(/^Across all 24 expiries \(23 of 24 expiries read\):/);
    expect(openInterestHistorySentence([])).toBeNull();
  });
});

describe("OpenInterestHistory", () => {
  it("draws from two sessions on", () => {
    render(<OpenInterestHistory history={TWO} />);
    expect(screen.getByTestId("options-oi-history")).toBeInTheDocument();
  });

  it("draws nothing from one session", () => {
    const { container } = render(<OpenInterestHistory history={TWO.slice(0, 1)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is an empty list in a report cached before it", () => {
    expect(OptionsReportSchema.parse(RAW_OPTIONS_REPORT).open_interest_history).toEqual([]);
  });
});
