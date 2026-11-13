import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import type { Insiders } from "../lib/insider-extract";
import { InsiderCard } from "./InsiderCard";

const BASE: Insiders = {
  filingCount: 38,
  firstFiling: "2026-05-29",
  lastFiling: "2026-11-06",
  bought: 0,
  buyers: 0,
  sold: 1_378_200_000,
  sellers: 5,
  planShare: 0.0153,
  routine: 32,
  holderBought: 0,
  holderSold: 0,
  soldShareOfMarketCap: 0.000313,
  boughtShareOfMarketCap: null,
  people: [
    { name: "STEVENS MARK A", role: "Director", net: -1_353_730_172 },
    { name: "Kress Colette", role: "EVP & Chief Financial Officer", net: -7_648_632 },
  ],
  narrative: "Selling dominated by one director.",
};

describe("InsiderCard", () => {
  it("says what happened in a sentence built from the numbers", () => {
    render(<InsiderCard ticker="NVDA" insiders={BASE} />);
    expect(screen.getByTestId("insider-headline")).toHaveTextContent(
      "Officers and directors sold $1.38B and bought nothing.",
    );
    expect(screen.getByTestId("insider-context")).toHaveTextContent(
      "1.5% of the selling was under pre-arranged 10b5-1 plans. The sales equal 0.03% of the company's market value.",
    );
  });

  it("shows bought, sold, plan share and routine filings as tiles", () => {
    render(<InsiderCard ticker="NVDA" insiders={BASE} />);
    const tiles = screen.getAllByTestId("insider-tile").map((t) => t.textContent);
    expect(tiles).toEqual([
      expect.stringContaining("$0"),
      expect.stringContaining("$1.38B"),
      expect.stringContaining("1.5%"),
      expect.stringContaining("32"),
    ]);
    expect(tiles[1]).toContain("5 officers and directors");
  });

  it("lists the largest traders with their role and direction", () => {
    render(<InsiderCard ticker="NVDA" insiders={BASE} />);
    const rows = screen.getAllByTestId("insider-person");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("STEVENS MARK A")).toBeInTheDocument();
    expect(rows[0]).toHaveTextContent("Director");
    expect(rows[0]).toHaveTextContent("sold $1.35B");
    expect(rows[1]).toHaveTextContent("sold $7.65M");
  });

  it("puts 10% holders on a line of their own", () => {
    render(<InsiderCard ticker="RIVN" insiders={{ ...BASE, holderBought: 1_000_299_999, holderSold: 0 }} />);
    expect(screen.getByTestId("insider-holders")).toHaveTextContent(
      "10% holders and other owners bought $1B (not counted above).",
    );
  });

  it("states a quiet half-year plainly", () => {
    render(
      <InsiderCard
        ticker="XOM"
        insiders={{ ...BASE, bought: 0, sold: 0, buyers: 0, sellers: 0, planShare: null, soldShareOfMarketCap: null, people: [], routine: 0 }}
      />,
    );
    expect(screen.getByTestId("insider-headline")).toHaveTextContent("No officer or director bought or sold.");
    expect(screen.queryByTestId("insider-person")).toBeNull();
  });

  it("says when there were no filings at all in the window", () => {
    render(
      <InsiderCard
        ticker="XOM"
        insiders={{ ...BASE, filingCount: 0, firstFiling: null, lastFiling: "2026-01-05", bought: null, sold: null, buyers: null, sellers: null, planShare: null, routine: null, people: [] }}
      />,
    );
    expect(screen.getByTestId("insider-headline")).toHaveTextContent(
      "No Form 4 filings about the company in the last 6 months. The most recent was filed Jan 5, 2026.",
    );
    expect(screen.queryAllByTestId("insider-tile")).toHaveLength(0);
  });

  it("names the filings the numbers come from", () => {
    render(<InsiderCard ticker="NVDA" insiders={BASE} />);
    expect(screen.getByTestId("insider-note")).toHaveTextContent("38 Form 4 filings, May 29 – Nov 6, 2026");
  });

  it("shows the card narrative", () => {
    render(<InsiderCard ticker="NVDA" insiders={BASE} />);
    expect(screen.getByTestId("card-narrative")).toHaveTextContent("Selling dominated by one director.");
  });
});
