/**
 * BusinessCard tests (Phase 4.4.A).
 *
 * Lightweight card surfacing yfinance's longBusinessSummary alongside
 * HQ + employee count. Renders nothing when the summary is empty so
 * the ContextBand can collapse cleanly for thinly-covered tickers.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { BusinessCard } from "./BusinessCard";
import type { Claim, ClaimValue, Section } from "../lib/schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "yfinance.business_info", fetched_at: "2026-05-04T01:00:00+00:00" },
    history: [],
  };
}

function section(claims: Claim[]): Section {
  return { title: "Business", claims, summary: "", confidence: "medium" };
}

const FULL: Claim[] = [
  claim(
    "Business description (from 10-K filing)",
    "Apple Inc. designs, manufactures, and markets smartphones.",
  ),
  claim("Headquarters location", "Cupertino, CA, United States"),
  claim("Full-time employee count", 164_000),
];

describe("BusinessCard", () => {
  it("renders the business summary text", () => {
    const { getByText } = render(
      <BusinessCard ticker="AAPL" section={section(FULL)} />,
    );
    expect(
      getByText(/Apple Inc\. designs, manufactures/),
    ).not.toBeNull();
  });

  it("renders HQ + employee count in the metadata row", () => {
    const { container } = render(
      <BusinessCard ticker="AAPL" section={section(FULL)} />,
    );
    const meta = container.querySelector("[data-testid='business-meta']");
    expect(meta).not.toBeNull();
    const text = meta!.textContent ?? "";
    expect(text).toMatch(/Cupertino/);
    // Employee count formatted with locale grouping.
    expect(text).toMatch(/164,000/);
  });

  it("renders nothing when the summary claim is missing/null", () => {
    const { container } = render(
      <BusinessCard
        ticker="AAPL"
        section={section([
          claim("Headquarters location", "Cupertino, CA"),
          claim("Full-time employee count", 164_000),
        ])}
      />,
    );
    // The component returns null → nothing rendered.
    expect(container.firstChild).toBeNull();
  });

  it("does not throw when the section is empty", () => {
    expect(() =>
      render(<BusinessCard ticker="AAPL" section={section([])} />),
    ).not.toThrow();
  });
});

// tasks/dogfood-2026-11.md #3 — long summaries clamp to ~3 lines.
describe("BusinessCard — long summaries", () => {
  const LONG = "Apple Inc. designs, manufactures, and markets smartphones. ".repeat(10);

  it("clamps a long summary and offers Show more", () => {
    render(<BusinessCard ticker="AAPL" section={section([claim("Business description (from 10-K filing)", LONG)])} />);
    const summary = screen.getByTestId("business-summary");
    expect(summary.className).toContain("line-clamp-3");
    const toggle = screen.getByRole("button", { name: "Show more" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(summary.className).not.toContain("line-clamp-3");
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  });

  it("leaves a short summary alone", () => {
    render(<BusinessCard ticker="AAPL" section={section(FULL)} />);
    expect(screen.getByTestId("business-summary").className).not.toContain("line-clamp-3");
    expect(screen.queryByRole("button", { name: /show more/i })).toBeNull();
  });
});

// 2026-11 layout pass — the comparison set, as links to each peer.
describe("BusinessCard — peers", () => {
  it("shows the sector and links each peer to its dashboard", async () => {
    const { MemoryRouter } = await import("react-router-dom");
    render(
      <MemoryRouter>
        <BusinessCard ticker="KO" section={section(FULL)} sector="consumer_staples" peers={["PEP", "PG"]} />
      </MemoryRouter>,
    );
    const peers = screen.getByTestId("business-peers");
    expect(peers).toHaveTextContent("Consumer staples");
    expect(screen.getByRole("link", { name: "PEP" })).toHaveAttribute("href", "/symbol/PEP");
  });

  it("leaves the block out without sector or peers", () => {
    render(<BusinessCard ticker="KO" section={section(FULL)} />);
    expect(screen.queryByTestId("business-peers")).toBeNull();
  });
});
