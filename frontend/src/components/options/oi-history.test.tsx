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

  it("gives no change from a short read, which would look like a drop", () => {
    const shortLast = [TWO[0], { ...TWO[1], expiries: 23 }];
    expect(text(openInterestHistorySentence(shortLast))).toMatch(
      /\(put\/call \*\*0\.88\*\*\)\. The change is left out: this session's read was short\.$/,
    );
    // A short first session: the change runs from the first whole read.
    const THREE = [{ ...TWO[0], date: "2026-11-13", expiries: 22 }, ...TWO];
    expect(text(openInterestHistorySentence(THREE))).toMatch(/calls \*\*up 10\.5%\*\* and puts \*\*up 2\.7%\*\* since Nov 16\.$/);
    // Every session short: nothing to compare.
    const allShort = TWO.map((h) => ({ ...h, expiries: 23 }));
    expect(text(openInterestHistorySentence(allShort))).toMatch(/\. Recorded daily from Nov 16\.$/);
  });
});

describe("OpenInterestHistory", () => {
  it("draws from two sessions on", () => {
    render(<OpenInterestHistory history={TWO} />);
    expect(screen.getByTestId("options-oi-history")).toBeInTheDocument();
  });

  it("leaves a short session out of the lines, and says so", () => {
    const three = [...TWO, { ...TWO[1], date: "2026-11-18", call: 4_000_000, expiries: 23 }];
    render(<OpenInterestHistory history={three} />);
    expect(screen.getByTestId("options-oi-history")).toHaveTextContent("1 session read short is left out of the lines.");
    expect(screen.getByRole("img", { name: /2 sessions/ })).toBeInTheDocument();
  });

  it("draws nothing with fewer than two whole reads", () => {
    const { container } = render(<OpenInterestHistory history={[TWO[0], { ...TWO[1], expiries: 23 }]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing from one session", () => {
    const { container } = render(<OpenInterestHistory history={TWO.slice(0, 1)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is an empty list in a report cached before it", () => {
    expect(OptionsReportSchema.parse(RAW_OPTIONS_REPORT).open_interest_history).toEqual([]);
  });
});
