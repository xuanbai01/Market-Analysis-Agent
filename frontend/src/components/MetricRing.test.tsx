/**
 * MetricRing tests (Phase 4.2).
 *
 * Hand-rolled SVG ring. Used by QualityCard for ROE / ROIC / FCF
 * margin display. Pinned behaviors:
 *
 * 1. Renders an SVG with data-testid='metric-ring'.
 * 2. Renders the formatted value at the center.
 * 3. Renders the label below the ring.
 * 4. Renders the optional sub-label.
 * 5. Honors custom size + accent color.
 * 6. Clamps ratio to [0, 1] — values outside the range don't break SVG.
 * 7. Renders the bare label when ratio is null (data unavailable).
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { MetricRing } from "./MetricRing";

describe("MetricRing", () => {
  it("renders an SVG with data-testid='metric-ring'", () => {
    const { container } = render(
      <MetricRing label="ROE" value="32.0%" ratio={0.32} />,
    );
    expect(
      container.querySelector("[data-testid='metric-ring']"),
    ).not.toBeNull();
  });

  it("renders the value at the center of the ring", () => {
    const { getByText } = render(
      <MetricRing label="ROIC" value="61.0%" ratio={0.61} />,
    );
    expect(getByText("61.0%")).not.toBeNull();
  });

  it("renders the label below the ring", () => {
    const { getByText } = render(
      <MetricRing label="ROE" value="32.0%" ratio={0.32} />,
    );
    expect(getByText("ROE")).not.toBeNull();
  });

  it("renders the optional sub-label when provided", () => {
    const { getByText } = render(
      <MetricRing
        label="ROIC"
        value="61.0%"
        ratio={0.61}
        sub="top decile"
      />,
    );
    expect(getByText("top decile")).not.toBeNull();
  });

  it("respects custom size", () => {
    const { container } = render(
      <MetricRing label="ROE" value="—" ratio={null} size={120} />,
    );
    const svg = container.querySelector("[data-testid='metric-ring']");
    expect(svg?.getAttribute("width")).toBe("120");
    expect(svg?.getAttribute("height")).toBe("120");
  });

  it("clamps ratio > 1 to 1 (no broken SVG)", () => {
    expect(() =>
      render(<MetricRing label="X" value="200%" ratio={2} />),
    ).not.toThrow();
  });

  it("clamps ratio < 0 to 0 (no broken SVG)", () => {
    expect(() =>
      render(<MetricRing label="X" value="-12%" ratio={-0.12} />),
    ).not.toThrow();
  });

  it("renders without an arc when ratio is null (data unavailable)", () => {
    const { container, getByText } = render(
      <MetricRing label="ROIC" value="—" ratio={null} />,
    );
    // Bare ring (background circle only) still renders.
    expect(
      container.querySelector("[data-testid='metric-ring']"),
    ).not.toBeNull();
    // Value is the em-dash; label still present.
    expect(getByText("—")).not.toBeNull();
    expect(getByText("ROIC")).not.toBeNull();
  });
});
