import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { MissingDataNote } from "./MissingDataNote";

describe("MissingDataNote", () => {
  it("renders nothing when every tool returned data", () => {
    const { container } = render(<MissingDataNote audit={["fetch_fundamentals: ok", "fetch_peers: ok"]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists what the report lacks and why", () => {
    render(
      <MissingDataNote
        audit={["extract_10k_risks_diff: empty", "fetch_annual_history: empty", "fetch_peers: error/RuntimeError"]}
      />,
    );
    const note = screen.getByTestId("missing-data");
    expect(note).toHaveTextContent("Not in this report:");
    expect(note).toHaveTextContent("10-K risk changes (no data)");
    expect(note).toHaveTextContent("ten-year history (no data)");
    expect(note).toHaveTextContent("peer comparison (source failed)");
  });
});
