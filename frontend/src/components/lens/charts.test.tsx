import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { CapexBars } from "./CapexBars";
import { DistributionChart } from "./DistributionChart";
import { LENS } from "./fixture";

describe("DistributionChart", () => {
  it("draws a dot per reported company-year, the median and the middle-50% band", () => {
    render(<DistributionChart report={LENS} />);
    expect(screen.getAllByTestId("lens-dot")).toHaveLength(8); // CCC missed 2023
    expect(screen.getByTestId("lens-median")).toBeInTheDocument();
    expect(screen.getByTestId("lens-iqr")).toBeInTheDocument();
  });

  it("labels each company directly at the latest year", () => {
    render(<DistributionChart report={LENS} />);
    expect(screen.getAllByTestId("lens-end-label").map((l) => l.textContent)).toEqual(["AAA", "CCC", "BBB"]);
  });

  it("starts the axis at 0%", () => {
    const { container } = render(<DistributionChart report={LENS} />);
    const labels = Array.from(container.querySelectorAll("text")).map((t) => t.textContent);
    expect(labels).toContain("0%");
  });

  it("ranks every company on hover, with the median and band", () => {
    render(<DistributionChart report={LENS} />);
    fireEvent.mouseEnter(screen.getAllByTestId("lens-column")[2]);
    const tip = screen.getByTestId("lens-tooltip");
    expect(tip).toHaveTextContent("CY2025");
    expect(tip).toHaveTextContent("median 10.0% · middle 50% 6.5%–17.5%");
    expect(tip.textContent?.indexOf("AAA")).toBeLessThan(tip.textContent?.indexOf("BBB") ?? 0);
  });
});

describe("CapexBars", () => {
  it("stacks one segment per company-year with spend, totals on top", () => {
    render(<CapexBars report={LENS} />);
    expect(screen.getAllByTestId("lens-segment")).toHaveLength(8);
    expect(screen.getAllByTestId("lens-bar-total").map((t) => t.textContent)).toEqual(["$22B", "$37B", "$53B"]);
  });

  it("lists each company's spend on hover, largest first", () => {
    render(<CapexBars report={LENS} />);
    fireEvent.mouseEnter(screen.getAllByTestId("lens-bar-column")[2]);
    const tip = screen.getByTestId("lens-bars-tooltip");
    expect(tip).toHaveTextContent("CY2025");
    expect(tip).toHaveTextContent("$53.0B");
    expect(tip.textContent?.indexOf("AAA")).toBeLessThan(tip.textContent?.indexOf("CCC") ?? 0);
  });
});

describe("narrow containers", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("never draws a negative width when the container measures tiny", () => {
    // A container caught mid-resize reported ~100 px; the inner width went
    // negative and the browser rejected the rects.
    class TinyObserver {
      constructor(private readonly cb: ResizeObserverCallback) {}
      observe() {
        this.cb([{ contentRect: { width: 100 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      }
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal("ResizeObserver", TinyObserver);
    const { container } = render(
      <>
        <DistributionChart report={LENS} />
        <CapexBars report={LENS} />
      </>,
    );
    const widths = Array.from(container.querySelectorAll("rect")).map((r) => Number(r.getAttribute("width")));
    expect(widths.length).toBeGreaterThan(0);
    expect(Math.min(...widths)).toBeGreaterThanOrEqual(0);
  });
});
