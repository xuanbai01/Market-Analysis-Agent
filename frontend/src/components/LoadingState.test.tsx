import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { LoadingState } from "./LoadingState";

describe("LoadingState", () => {
  it("names the ticker whose report is being generated", () => {
    render(<LoadingState symbol="AAPL" />);
    expect(screen.getByText("Generating report for AAPL…")).toBeInTheDocument();
  });

  // tasks/dogfood-2026-11.md #2 — the page-code fallback used to pass
  // "loading" as the ticker: "Generating report for loading…".
  it("shows only the skeleton when no report is being generated", () => {
    render(<LoadingState />);
    expect(screen.queryByText(/Generating report/)).toBeNull();
    expect(screen.getByTestId("dashboard-skeleton")).toBeInTheDocument();
  });
});
