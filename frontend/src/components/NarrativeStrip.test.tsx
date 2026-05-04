/**
 * NarrativeStrip — Phase 4.4.B primitive tests.
 *
 * The strip renders the LLM's per-card 1-2 sentence headline at the
 * bottom of each dedicated dashboard card (Quality, Earnings,
 * PerShareGrowth, RiskDiff, Macro). It returns null when the
 * narrative is absent or whitespace-only so older cached rows (and
 * sections where the model declined to write one) don't render an
 * empty card-within-card.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { NarrativeStrip } from "./NarrativeStrip";

describe("NarrativeStrip", () => {
  it("renders the prose when text is provided", () => {
    const { getByTestId } = render(
      <NarrativeStrip text="Loss is narrowing. EPS climbed steadily." />,
    );
    const el = getByTestId("card-narrative");
    expect(el.textContent).toContain("Loss is narrowing.");
  });

  it("returns null when text is null", () => {
    const { container } = render(<NarrativeStrip text={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null when text is undefined", () => {
    const { container } = render(<NarrativeStrip text={undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null when text is empty string or whitespace", () => {
    const empty = render(<NarrativeStrip text="" />);
    expect(empty.container.firstChild).toBeNull();
    const spaces = render(<NarrativeStrip text="   " />);
    expect(spaces.container.firstChild).toBeNull();
  });
});
