import { describe, expect, it } from "vitest";

import { endingLabel, heldLabel, monthLabel, positionName, summarySentence } from "./journal-text";
import type { JournalPosition } from "./owner-schemas";

const base: JournalPosition = {
  id: "order-1", account: 1, underlying: "NVDA", structure: "short put", legs: [], opened_at: "2026-11-01T15:00:00+00:00",
  closed_at: null, days_held: null, status: "open", ended_by: null, origin: null, origin_position: null, open_cash: 300,
  close_cash: null, fees: 1.1, realized: null, rolled_from: null, rolled_to: null, note: null, transactions: [1],
};

const text = (s: (string | { strong: string })[]) => s.map((p) => (typeof p === "string" ? p : `**${p.strong}**`)).join("");

describe("journal words", () => {
  it("says how a position stands or ended", () => {
    expect(endingLabel(base)).toBe("open");
    expect(endingLabel({ ...base, status: "partly_closed", ended_by: "closed" })).toBe("partly closed");
    expect(endingLabel({ ...base, status: "closed", ended_by: "expired" })).toBe("expired");
    expect(endingLabel({ ...base, status: "closed", ended_by: "assigned" })).toBe("assigned");
    expect(endingLabel({ ...base, status: "closed", ended_by: "mixed" })).toBe("closed in parts");
  });

  it("counts the days held", () => {
    expect(heldLabel(null)).toBe("—");
    expect(heldLabel(0)).toBe("same day");
    expect(heldLabel(1)).toBe("1 day");
    expect(heldLabel(20)).toBe("20 days");
  });

  it("names a position by what and when", () => {
    expect(positionName(base)).toBe("the short put opened Nov 1");
  });

  it("labels a month", () => {
    expect(monthLabel("2026-11")).toBe("Nov 2026");
  });

  it("sums the closed positions in facts, not advice", () => {
    expect(text(summarySentence({ realized: 1234.5, closed: 12, profitable: 8, partly: 0, unpriced: 0, average_days: 9.4, fees: 56.2 }))).toBe(
      "**12** positions closed, **8** at a profit (**67%**), held **9 days** on average. Realized: **+$1,235** after **$56** in fees.",
    );
    expect(text(summarySentence({ realized: 0, closed: 0, profitable: 0, partly: 0, unpriced: 0, average_days: null, fees: 0 }))).toBe("Nothing closed yet.");
  });

  it("says the realized figure includes partly closed positions", () => {
    expect(text(summarySentence({ realized: 150, closed: 0, profitable: 0, partly: 1, unpriced: 0, average_days: null, fees: 2 }))).toBe(
      "Nothing closed in full yet. Realized: **+$150** after **$2** in fees, from **1** partly closed position.",
    );
  });

  it("counts apart what closed without a computed P&L", () => {
    expect(text(summarySentence({ realized: 200, closed: 1, profitable: 1, partly: 0, unpriced: 2, average_days: 3, fees: 1 }))).toBe(
      "**1** position closed, **1** at a profit (**100%**), held **3 days** on average. Realized: **+$200** after **$1** in fees. **2** more closed without a computed P&L.",
    );
    expect(text(summarySentence({ realized: 0, closed: 0, profitable: 0, partly: 0, unpriced: 1, average_days: null, fees: 0 }))).toBe(
      "**1** position closed without a computed P&L.",
    );
  });
});
