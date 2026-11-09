import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { MarketStrip } from "./MarketStrip";
import { fetchMarketOverview } from "../lib/api";
import type { MarketOverview } from "../lib/schemas";

vi.mock("../lib/api", () => ({ fetchMarketOverview: vi.fn() }));
const fetchMock = vi.mocked(fetchMarketOverview);

function quote(
  symbol: string,
  label: string,
  kind: string,
  unit: "points" | "percent" | "usd",
  price: number,
  change: number,
  change_percent: number,
) {
  return { symbol, label, kind, unit, price, change, change_percent, as_of: "2026-11-06" };
}

const OVERVIEW: MarketOverview = {
  quotes: [
    quote("^GSPC", "S&P 500", "index", "points", 7376.86, 23.13, 0.3146),
    quote("^NDX", "Nasdaq 100", "index", "points", 26989.99, 360.18, 1.3525),
    quote("^DJI", "Dow Jones", "index", "points", 51285.73, -237.33, -0.4606),
    quote("^VIX", "VIX", "volatility", "points", 25.64, -2.54, -9.01),
    quote("^TNX", "US 10Y", "rate", "percent", 4.859, 0.022, 0.45),
    quote("BTC-USD", "Bitcoin", "crypto", "usd", 74790.86, -956.72, -1.263),
  ],
  sentiment: {
    score: 1.8,
    rating: "extreme_fear",
    as_of: "2026-11-06",
    methodology: "Our estimate, not CNN's index. Each indicator is ranked against its own past year.",
    components: [
      { key: "momentum", label: "Market momentum", score: 5.2, description: "S&P 500 is 2.8% below its 125-day average" },
      { key: "volatility", label: "Volatility", score: 0.8, description: "VIX is 51.5% above its 50-day average" },
    ],
  },
  generated_at: "2026-11-08T18:00:00Z",
};

function renderStrip() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MarketStrip />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
});

describe("MarketStrip", () => {
  it("lists the quotes in order, with the fear & greed estimate after VIX", async () => {
    fetchMock.mockResolvedValue(OVERVIEW);
    renderStrip();
    await screen.findByTestId("sentiment-chip");
    const strip = screen.getByRole("region", { name: "Markets" });
    const order = Array.from(strip.querySelectorAll("[data-testid='market-quote'], [data-testid='sentiment-chip']")).map(
      (el) => el.getAttribute("data-symbol") ?? "F&G",
    );
    expect(order).toEqual(["^GSPC", "^NDX", "^DJI", "^VIX", "F&G", "^TNX", "BTC-USD"]);
  });

  it("shows each price in its unit with the day's move", async () => {
    fetchMock.mockResolvedValue(OVERVIEW);
    renderStrip();
    const spx = await screen.findByTitle(/S&P 500 · as of Nov 6/);
    expect(spx).toHaveTextContent("7,376.86");
    expect(spx).toHaveTextContent("▲ +0.31%");
    expect(screen.getByTitle(/US 10Y/)).toHaveTextContent("4.86%");
    expect(screen.getByTitle(/US 10Y/)).toHaveTextContent("+2 bps");
    expect(screen.getByTitle(/Bitcoin/)).toHaveTextContent("$74,791");
    expect(screen.getByTitle(/Bitcoin/)).toHaveTextContent("▼ -1.26%");
  });

  it("labels fear & greed as an estimate", async () => {
    fetchMock.mockResolvedValue(OVERVIEW);
    renderStrip();
    const chip = await screen.findByTestId("sentiment-chip");
    expect(chip).toHaveTextContent("est.");
    expect(chip).toHaveTextContent("2");
    expect(chip).toHaveTextContent("Extreme fear");
    expect(chip).toHaveAccessibleName(/our estimate: 2, Extreme fear/);
  });

  it("opens how the estimate is built, and closes on Escape", async () => {
    fetchMock.mockResolvedValue(OVERVIEW);
    renderStrip();
    const chip = await screen.findByTestId("sentiment-chip");
    expect(chip).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(chip);
    expect(chip).toHaveAttribute("aria-expanded", "true");
    const panel = screen.getByRole("region", { name: /how the fear and greed estimate is built/i });
    expect(within(panel).getAllByTestId("sentiment-component")).toHaveLength(2);
    expect(panel).toHaveTextContent("S&P 500 is 2.8% below its 125-day average");
    expect(panel).toHaveTextContent("not CNN's index");
    expect(within(panel).getByRole("link", { name: /CNN's index/ })).toHaveAttribute(
      "target",
      "_blank",
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("region", { name: /how the fear and greed/i })).toBeNull();
  });

  it("places the meter marker at the score", async () => {
    fetchMock.mockResolvedValue(OVERVIEW);
    renderStrip();
    const chip = await screen.findByTestId("sentiment-chip");
    expect(within(chip).getByTestId("meter-marker")).toHaveStyle({ left: "1.8%" });
  });

  it("leaves out the fear & greed chip when there is no estimate", async () => {
    fetchMock.mockResolvedValue({ ...OVERVIEW, sentiment: null });
    renderStrip();
    await screen.findByTitle(/S&P 500/);
    expect(screen.queryByTestId("sentiment-chip")).toBeNull();
  });

  it("hides itself when the request fails or returns nothing", async () => {
    fetchMock.mockRejectedValue(new Error("down"));
    const { container, unmount } = renderStrip();
    await vi.waitFor(() => expect(container.querySelector("[data-testid='market-strip']")).toBeNull());
    unmount();

    fetchMock.mockResolvedValue({ quotes: [], sentiment: null, generated_at: "2026-11-08T18:00:00Z" });
    const second = renderStrip();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await vi.waitFor(() =>
      expect(second.container.querySelector("[data-testid='market-strip']")).toBeNull(),
    );
  });

  it("holds its height with placeholders while loading", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderStrip();
    expect(screen.getByRole("region", { name: "Markets" })).toHaveAttribute("aria-busy", "true");
  });
});
