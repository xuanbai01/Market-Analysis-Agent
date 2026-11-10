/**
 * price-range tests (Phase 4.3.B.1).
 *
 * The hero card's range pills (1D / 5D / 1M / 3M / 1Y / 5Y) all share
 * the same backend endpoint at three cadences (60D / 1Y / 5Y). For
 * sub-3M ranges, the backend returns 60 days of data and the frontend
 * slices client-side. ``sliceForRange`` is the slicer.
 *
 * Pinned behaviors:
 *
 * 1. "60D" / "3M" / "1Y" / "5Y" return the data unchanged — the backend
 *    already constrained the range, no client-side slicing needed.
 * 2. "1M" returns the last ~22 trading days from a 60D fetch.
 * 3. "5D" returns the last 5 points.
 * 4. "1D" returns the last 2 points (so there's something to draw — a
 *    single point isn't a chartable line). When fewer than 2 points
 *    exist, returns whatever there is.
 * 5. Empty input returns empty output regardless of range.
 * 6. The slicer never adds points it didn't receive.
 */
import { describe, expect, it } from "vitest";

import { sliceForRange, type UiRange } from "./price-range";
import type { PricePoint } from "./schemas";

function fakePoints(n: number): PricePoint[] {
  // Synthetic series 1..n so it's easy to identify which points
  // survived the slice by their close value.
  return Array.from({ length: n }, (_, i) => ({
    ts: `2026-01-${String((i % 28) + 1).padStart(2, "0")}T00:00:00Z`,
    close: i + 1,
    volume: 1_000_000,
  }));
}

describe("sliceForRange", () => {
  it("returns input unchanged for 60D / 3M / 1Y / 5Y (backend-constrained ranges)", () => {
    const data = fakePoints(60);
    for (const range of ["60D", "3M", "1Y", "5Y"] as UiRange[]) {
      expect(sliceForRange(data, range)).toEqual(data);
    }
  });

  it("returns the last 22 points for 1M", () => {
    const data = fakePoints(60);
    const out = sliceForRange(data, "1M");
    expect(out.length).toBe(22);
    // Last point preserved; first sliced point is index 38 (60 − 22).
    expect(out[out.length - 1].close).toBe(60);
    expect(out[0].close).toBe(39);
  });

  it("returns the last 5 points for 5D", () => {
    const data = fakePoints(60);
    const out = sliceForRange(data, "5D");
    expect(out.length).toBe(5);
    expect(out[out.length - 1].close).toBe(60);
    expect(out[0].close).toBe(56);
  });

  it("returns whatever exists when input is shorter than the requested slice", () => {
    const tiny = fakePoints(3);
    expect(sliceForRange(tiny, "1M")).toEqual(tiny);
    expect(sliceForRange(tiny, "5D")).toEqual(tiny);
    expect(sliceForRange(tiny, "5D").length).toBe(3);
  });

  it("returns empty array when given empty input", () => {
    for (const range of ["5D", "1M", "3M", "1Y", "5Y"] as UiRange[]) {
      expect(sliceForRange([], range)).toEqual([]);
    }
  });

  it("never invents points (output is always a slice of input)", () => {
    const data = fakePoints(60);
    for (const range of ["5D", "1M"] as UiRange[]) {
      const out = sliceForRange(data, range);
      for (const p of out) {
        expect(data).toContain(p);
      }
    }
  });
});

// ── YTD ──────────────────────────────────────────────────────────────
//
// Sliced from the 1Y feed. Year-to-date change is measured from the
// previous year's last close, so the slice keeps that one bar as its
// starting point.

describe("sliceForRange YTD", () => {
  function bar(ts: string, close: number): PricePoint {
    return { ts, close, volume: 1_000 };
  }

  const YEAR_FEED = [
    bar("2025-11-10T05:00:00+00:00", 80),
    bar("2025-12-30T05:00:00+00:00", 84),
    bar("2025-12-31T05:00:00+00:00", 85),
    bar("2026-01-02T05:00:00+00:00", 86),
    bar("2026-06-01T04:00:00+00:00", 90),
    bar("2026-11-06T05:00:00+00:00", 95.67),
  ];

  it("starts at the previous year's last close and keeps the year since", () => {
    const out = sliceForRange(YEAR_FEED, "YTD");
    expect(out.map((p) => p.ts.slice(0, 10))).toEqual(["2025-12-31", "2026-01-02", "2026-06-01", "2026-11-06"]);
  });

  it("takes the year from the latest bar, not the clock", () => {
    const lastYear = YEAR_FEED.slice(0, 3); // latest bar is 2025-12-31
    expect(sliceForRange(lastYear, "YTD").map((p) => p.ts.slice(0, 10))).toEqual([
      "2025-11-10",
      "2025-12-30",
      "2025-12-31",
    ]);
  });

  it("keeps the whole year when there is no earlier bar", () => {
    const thisYearOnly = YEAR_FEED.slice(3);
    expect(sliceForRange(thisYearOnly, "YTD")).toEqual(thisYearOnly);
  });

  it("returns empty for empty input", () => {
    expect(sliceForRange([], "YTD")).toEqual([]);
  });
});

// ── Trailing 1Y / 5Y ─────────────────────────────────────────────────
//
// The backend pads its feeds (1Y = 400 days, 5Y = 2,000) for its cache
// check; the pills used to draw them whole — 13 months and 5½ years.

describe("sliceForRange 1Y / 5Y", () => {
  function bar(ts: string, close: number): PricePoint {
    return { ts, close, volume: 1_000 };
  }

  it("1Y starts at the last close on or before the date a year before the latest bar", () => {
    const feed = [
      bar("2025-10-06T04:00:00Z", 60),
      bar("2025-11-05T05:00:00Z", 64),
      bar("2025-11-06T05:00:00Z", 65), // a year before 2026-11-06: the base
      bar("2025-11-07T05:00:00Z", 66),
      bar("2026-11-06T05:00:00Z", 95),
    ];
    expect(sliceForRange(feed, "1Y").map((p) => p.ts.slice(0, 10))).toEqual([
      "2025-11-06",
      "2025-11-07",
      "2026-11-06",
    ]);
  });

  it("5Y keeps five years from the latest bar", () => {
    const feed = [
      bar("2021-03-01T05:00:00Z", 30),
      bar("2021-11-05T04:00:00Z", 40),
      bar("2021-11-08T05:00:00Z", 41),
      bar("2026-11-06T05:00:00Z", 95),
    ];
    // 5 years before 2026-11-06 05:00 is 2021-11-06 05:00; the last
    // close on or before it (Nov 5) is the base.
    expect(sliceForRange(feed, "5Y").map((p) => p.ts.slice(0, 10))).toEqual([
      "2021-11-05",
      "2021-11-08",
      "2026-11-06",
    ]);
  });

  it("keeps the whole feed when it is shorter than the range", () => {
    const feed = [bar("2026-06-01T04:00:00Z", 80), bar("2026-11-06T05:00:00Z", 95)];
    expect(sliceForRange(feed, "1Y")).toEqual(feed);
  });
});
