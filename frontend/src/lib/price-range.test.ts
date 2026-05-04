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

  it("returns the last 2 points for 1D so there's a line to draw", () => {
    const data = fakePoints(60);
    const out = sliceForRange(data, "1D");
    expect(out.length).toBe(2);
    expect(out[out.length - 1].close).toBe(60);
    expect(out[0].close).toBe(59);
  });

  it("returns whatever exists when input is shorter than the requested slice", () => {
    const tiny = fakePoints(3);
    expect(sliceForRange(tiny, "1M")).toEqual(tiny);
    expect(sliceForRange(tiny, "5D")).toEqual(tiny);
    expect(sliceForRange(tiny, "1D").length).toBe(2);
  });

  it("returns empty array when given empty input", () => {
    for (const range of ["1D", "5D", "1M", "3M", "1Y", "5Y"] as UiRange[]) {
      expect(sliceForRange([], range)).toEqual([]);
    }
  });

  it("never invents points (output is always a slice of input)", () => {
    const data = fakePoints(60);
    for (const range of ["1D", "5D", "1M"] as UiRange[]) {
      const out = sliceForRange(data, range);
      for (const p of out) {
        expect(data).toContain(p);
      }
    }
  });
});
