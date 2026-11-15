import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { ApiError } from "../../lib/api";
import { fetchOptionsChain, fetchOptionsReport } from "../../lib/options-api";
import { OptionsReportSchema } from "../../lib/options-schemas";
import { clearOwnerKey, getOwnerKey, setOwnerKey } from "../../lib/owner";
import { fetchOwnerPositions } from "../../lib/owner-api";
import { type OwnerPositions, OwnerPositionsSchema } from "../../lib/owner-schemas";
import { RAW_OPTIONS_REPORT } from "../options/fixture";
import PositionsPage from "./PositionsPage";

vi.mock("../../lib/owner-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/owner-api")>()),
  fetchOwnerPositions: vi.fn(),
}));
vi.mock("../../lib/options-api", () => ({ fetchOptionsReport: vi.fn(), fetchOptionsChain: vi.fn() }));

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
const quote = (mark: number, extra: object = {}) => ({ bid: mark - 0.05, ask: mark + 0.05, mark, iv: null, delta: null, gamma: null, theta: null, vega: null, updated_at: "2026-11-16T15:00:00Z", ...extra });

const POSITIONS: OwnerPositions = OwnerPositionsSchema.parse({
  as_of: "2026-11-16T15:00:05Z",
  accounts: 1,
  source: "tastytrade",
  groups: [
    {
      underlying: "NVDA", symbol: "NVDA", quote: quote(163.2), expiries: ["2026-12-11"],
      legs: [
        { account: 1, kind: "stock", symbol: "NVDA", quantity: 100, multiplier: 1, average_open: 150, quote: quote(163.2) },
        {
          account: 1, kind: "call", symbol: "NVDA  261211C00175000", expiry: "2026-12-11", strike: 175, quantity: -1, multiplier: 100, average_open: 4,
          quote: quote(3.2, { iv: 0.58, delta: 0.3, gamma: 0.02, theta: -0.12, vega: 0.18 }),
        },
      ],
    },
    {
      underlying: "SPY", symbol: "SPY", quote: quote(671), expiries: ["2026-12-18"],
      legs: [
        {
          account: 1, kind: "put", symbol: "SPY   261218P00650000", expiry: "2026-12-18", strike: 650, quantity: 1, multiplier: 100, average_open: 5,
          quote: quote(4.1, { iv: 0.16, delta: -0.25, gamma: 0.01, theta: -0.15, vega: 0.6 }),
        },
      ],
    },
  ],
  unanalysed: [{ account: 1, instrument_type: "Future", symbol: "/ESZ6", quantity: 1 }],
});

let client: QueryClient;

function renderPage() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PositionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(fetchOptionsReport).mockImplementation(async (s) => (s === "NVDA" ? REPORT : Promise.reject(new ApiError({ status: 404, title: "no" }))));
  vi.mocked(fetchOptionsChain).mockImplementation(async (s) => (s === "NVDA" ? REPORT.chain! : Promise.reject(new ApiError({ status: 404, title: "no" }))));
  vi.spyOn(api, "fetchMarketPrices").mockImplementation(async (ticker) => ({
    ticker, range: "5Y", prices: Array.from({ length: 300 }, (_, i) => ({ ts: `d${i}`, close: 100 + i * 0.1, volume: 1 })), latest: { ts: "x", close: 130, delta_abs: 0, delta_pct: 0 },
  }) as unknown as Awaited<ReturnType<typeof api.fetchMarketPrices>>);
});

afterEach(() => {
  clearOwnerKey();
  vi.mocked(fetchOwnerPositions).mockReset();
  vi.restoreAllMocks();
});

describe("PositionsPage", () => {
  it("asks for the owner key before anything else", () => {
    renderPage();
    expect(screen.getByTestId("owner-unlock")).toBeInTheDocument();
    expect(fetchOwnerPositions).not.toHaveBeenCalled();
  });

  it("shows each underlying with its legs, Greeks, payoff and what our data says", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue(POSITIONS);
    renderPage();
    const groups = await screen.findAllByTestId("position-group");
    expect(groups).toHaveLength(2);
    expect(fetchOwnerPositions).toHaveBeenCalledWith("k".repeat(40));
    // The holdings' option reports are read without recording a view.
    await waitFor(() => expect(fetchOptionsReport).toHaveBeenCalledWith("NVDA", { track: false }));
    expect(fetchOptionsChain).toHaveBeenCalledWith("NVDA", "2026-12-11", { track: false });
    expect(screen.getByTestId("positions-asof")).toHaveTextContent("Live · tastytrade");
    expect(screen.getByTestId("positions-totals")).toBeInTheDocument();
    const nvda = groups[0];
    expect(within(nvda).getByTestId("position-group-summary")).toHaveTextContent("NVDA: 100 shares and 1 short Dec 11 $175 call.");
    expect(within(nvda).getAllByRole("row")).toHaveLength(3); // header and two legs
    expect(within(nvda).getByTestId("position-greeks")).toHaveTextContent(/Moves like 70 shares/);
    expect(within(nvda).getByTestId("position-payoff")).toBeInTheDocument();
    expect(within(nvda).getByTestId("position-whatif-summary")).toHaveTextContent(/At today's price and IVs/);
    await waitFor(() => expect(within(nvda).getByTestId("position-market")).toHaveTextContent(/not a forecast/));
    await waitFor(() => expect(within(nvda).getByTestId("position-history")).toHaveTextContent(/past moves, not a forecast/));
    expect(within(nvda).getByRole("link", { name: /NVDA options/ })).toHaveAttribute("href", "/options/NVDA");
    expect(screen.getByTestId("positions-unanalysed")).toHaveTextContent("/ESZ6 · Future · 1");
    expect(screen.getByTestId("positions-disclaimer")).toHaveTextContent(/nothing here is advice/);
  });

  it("forgets a key the server refuses and asks again", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockRejectedValue(new ApiError({ status: 403, title: "This needs the owner key." }));
    renderPage();
    expect(await screen.findByTestId("owner-unlock")).toBeInTheDocument();
    expect(getOwnerKey()).toBeNull();
    await waitFor(() => expect(client.getQueryData(["owner-positions"])).toBeUndefined());
  });

  it("drops the positions from memory once the key goes", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue(POSITIONS);
    renderPage();
    await screen.findAllByTestId("position-group");
    expect(client.getQueryData(["owner-positions"])).toBeDefined();
    act(() => clearOwnerKey());
    expect(await screen.findByTestId("owner-unlock")).toBeInTheDocument();
    await waitFor(() => expect(client.getQueryData(["owner-positions"])).toBeUndefined());
  });

  it("says when the copy is old or cut short", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue({ ...POSITIONS, stale: true, truncated: true });
    renderPage();
    const asOf = await screen.findByTestId("positions-asof");
    expect(asOf).toHaveTextContent(/last copy read/);
    expect(asOf).toHaveTextContent(/some are left out/);
  });

  it("says when nothing is open", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue({ ...POSITIONS, groups: [], unanalysed: [] });
    renderPage();
    expect(await screen.findByTestId("positions-empty")).toHaveTextContent("No open positions.");
  });

  it("shows a server error that isn't about the key", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockRejectedValue(new ApiError({ status: 503, title: "tastytrade didn't answer" }));
    renderPage();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(getOwnerKey()).not.toBeNull();
  });
});
