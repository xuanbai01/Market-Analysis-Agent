import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RealizedByMonth } from "./RealizedByMonth";

const MONTHS = [
  { month: "2026-09", realized: 420.5 },
  { month: "2026-10", realized: -180.25 },
  { month: "2026-11", realized: 95 },
];

describe("RealizedByMonth", () => {
  it("draws a bar a month, gains up and losses down from one zero line", () => {
    render(<RealizedByMonth months={MONTHS} width={480} />);
    const bars = screen.getAllByTestId("realized-bar");
    expect(bars.map((b) => b.getAttribute("data-sign"))).toEqual(["gain", "loss", "gain"]);
    expect(screen.getByTestId("realized-zero-line")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName(/Realized P&L by month, Sep 2026 to Nov 2026/);
  });

  it("gives the month and its figure on hover", () => {
    render(<RealizedByMonth months={MONTHS} width={480} />);
    fireEvent.mouseEnter(screen.getAllByTestId("realized-hit")[1]);
    expect(screen.getByTestId("realized-tooltip")).toHaveTextContent("Oct 2026");
    expect(screen.getByTestId("realized-tooltip")).toHaveTextContent("−$180.25");
  });

  it("draws nothing with no closed month", () => {
    const { container } = render(<RealizedByMonth months={[]} width={480} />);
    expect(container).toBeEmptyDOMElement();
  });
});
