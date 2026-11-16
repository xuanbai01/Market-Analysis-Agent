import { describe, expect, it } from "vitest";

import { inRange, ivHistorySentence, ivHistoryStats, latest } from "./iv-history-text";
import type { IvHistory, IvPoint } from "./owner-schemas";

function point(i: number, iv: number | null = 0.3, rv20: number | null = 0.25): IvPoint {
  const d = new Date(Date.UTC(2024, 0, 1) + i * 86_400_000).toISOString().slice(0, 10);
  return { date: d, close: 100 + i, iv, rv20 };
}

function history(over: Partial<IvHistory> = {}): IvHistory {
  return {
    symbol: "NVDA",
    as_of: "2026-11-16T15:00:00Z",
    metrics: { iv_index: 0.412, iv30: 0.415, iv_rank: 0.62, iv_percentile: 0.71, hv30: 0.352, hv60: 0.38, hv90: null,
               updated_at: null },
    points: Array.from({ length: 300 }, (_, i) => point(i, 0.2 + i / 1000, 0.25)),
    year: { sessions: 252, iv_low: 0.248, iv_high: 0.499, iv_median: 0.374, iv_rank: 1, iv_percentile: 0.996 },
    iv_since: "2024-01-01",
    complete: true,
    source: "tastytrade",
    ...over,
  };
}

const text = (s: ReturnType<typeof ivHistorySentence>) =>
  (s ?? []).map((part) => (typeof part === "string" ? part : part.strong)).join("");

describe("ivHistorySentence", () => {
  it("places today's IV in the past year and against what the stock moved", () => {
    expect(text(ivHistorySentence(history()))).toBe(
      "IV is 49.9%, higher than on 100% of the past year's sessions (from 24.8% to 49.9%). " +
        "Realized volatility over the last 20 sessions is 25.0%, 24.9 points below IV.",
    );
  });

  it("says how many sessions when there's less than a year", () => {
    const h = history({ year: { sessions: 40, iv_low: 0.2, iv_high: 0.5, iv_median: 0.3, iv_rank: 0.5, iv_percentile: 0.5 } });
    expect(text(ivHistorySentence(h))).toContain("higher than on 50% of the 40 sessions with an IV");
  });

  it("says realized volatility is above IV when it is", () => {
    const h = history({ points: [point(0, 0.2, 0.3), point(1, 0.2, 0.3)] });
    expect(text(ivHistorySentence(h))).toContain("10.0 points above IV");
  });

  it("has nothing to say without an IV", () => {
    expect(ivHistorySentence(history({ points: [point(0, null), point(1, null)] }))).toBeNull();
  });
});

describe("ivHistoryStats", () => {
  it("gives tastytrade's own figures, a dash for a missing one", () => {
    const rows = Object.fromEntries(ivHistoryStats(history()).map((r) => [r.label, r.value]));
    expect(rows["IV rank (tastytrade)"]).toBe("62%");
    expect(rows["IV percentile (tastytrade)"]).toBe("71%");
    expect(rows["HV30 / HV60 / HV90"]).toBe("35.2% / 38.0% / —");
    expect(rows["IV since"]).toBe("Jan 1, 2024");
  });
});

describe("inRange and latest", () => {
  const points = Array.from({ length: 1000 }, (_, i) => point(i));

  it("keeps the last year, three years or all of the sessions", () => {
    expect(inRange(points, "1Y")).toHaveLength(252);
    expect(inRange(points, "3Y")).toHaveLength(756);
    expect(inRange(points, "All")).toHaveLength(1000);
    expect(inRange(points, "1Y")[251]).toBe(points[999]);
  });

  it("takes the last value a series has", () => {
    expect(latest([point(0, 0.3), point(1, null)], "iv")).toBe(0.3);
    expect(latest([point(0, null)], "iv")).toBeNull();
  });
});
