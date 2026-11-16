import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { ApiError } from "../../lib/api";
import { fetchOptionsChain, fetchOptionsReport } from "../../lib/options-api";
import { OptionsReportSchema, PositioningSchema } from "../../lib/options-schemas";
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

// The fixtures' expiries are in December 2026: the page reads the clock.
const NOW = new Date("2026-11-16T15:00:10Z");

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
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  vi.mocked(fetchOptionsReport).mockImplementation(async (s) => (s === "NVDA" ? REPORT : Promise.reject(new ApiError({ status: 404, title: "no" }))));
  vi.mocked(fetchOptionsChain).mockImplementation(async (s) => (s === "NVDA" ? REPORT.chain! : Promise.reject(new ApiError({ status: 404, title: "no" }))));
  vi.spyOn(api, "fetchMarketPrices").mockImplementation(async (ticker) => ({
    ticker, range: "5Y", prices: Array.from({ length: 300 }, (_, i) => ({ ts: `d${i}`, close: 100 + i * 0.1, volume: 1 })), latest: { ts: "x", close: 130, delta_abs: 0, delta_pct: 0 },
  }) as unknown as Awaited<ReturnType<typeof api.fetchMarketPrices>>);
});

afterEach(() => {
  vi.useRealTimers();
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

  it("says when a holding's option context can't be read", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue(POSITIONS);
    renderPage();
    const spy = await screen.findAllByTestId("position-group");
    // The fixture's options routes only know NVDA: SPY's card says so.
    await waitFor(() => expect(within(spy[1]).getByTestId("position-context-missing")).toHaveTextContent(/SPY.s option data couldn.t be read/));
  });

  it("reads option context for the first 10 underlyings only", async () => {
    // Each cold read spends one of the hour's options lookups (60 an IP).
    const groups = Array.from({ length: 12 }, (_, i) => ({ ...POSITIONS.groups[1], underlying: `T${i}`, symbol: `T${i}` }));
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue({ ...POSITIONS, groups });
    renderPage();
    const cards = await screen.findAllByTestId("position-group");
    expect(cards).toHaveLength(12);
    await waitFor(() => expect(fetchOptionsReport).toHaveBeenCalledTimes(10));
    expect(vi.mocked(fetchOptionsReport).mock.calls.map(([s]) => s)).not.toContain("T10");
    expect(within(cards[10]).getByTestId("position-context-skipped")).toHaveTextContent(/first 10/);
    expect(within(cards[9]).queryByTestId("position-context-skipped")).toBeNull();
  });

  it("asks for the held expiry only once the report is in", async () => {
    // The report reads several expiries; the held one is then often free.
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue(POSITIONS);
    renderPage();
    const [, spy] = await screen.findAllByTestId("position-group");
    await waitFor(() => expect(within(spy).getByTestId("position-context-missing")).toBeInTheDocument());
    expect(vi.mocked(fetchOptionsChain).mock.calls.map(([s]) => s)).not.toContain("SPY"); // its report failed
  });

  it("leaves out max pain when the chain has none", async () => {
    const positioning = PositioningSchema.parse({
      call_open_interest: 1000, put_open_interest: 800, put_call: 0.8, max_pain: null, call_gex: 1, put_gex: -1, net_gex: 0,
      call_dex: 1, put_dex: -1, net_dex: 0, call_wall: 175, put_wall: 150, gamma_flip: null, assumption: "Dealers long calls, short puts.",
    });
    vi.mocked(fetchOptionsChain).mockResolvedValue({ ...REPORT.chain!, positioning });
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue(POSITIONS);
    renderPage();
    const [nvda] = await screen.findAllByTestId("position-group");
    await waitFor(() => expect(within(nvda).getByTestId("position-market")).toHaveTextContent(/not a forecast/));
    expect(within(nvda).getByTestId("position-walls")).toHaveTextContent("calls $175"); // the positioning drew
    expect(within(nvda).queryByTestId("position-maxpain")).toBeNull();
  });

  it("keeps its untracked reads out of the options page's cache", async () => {
    // Under the options page's keys, a visit there inside the staleTime
    // would be served this copy and never reach the server: no view recorded.
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue(POSITIONS);
    renderPage();
    const [nvda] = await screen.findAllByTestId("position-group");
    await waitFor(() => expect(within(nvda).getByTestId("position-market")).toHaveTextContent(/not a forecast/));
    expect(client.getQueryData(["options", "NVDA"])).toBeUndefined();
    expect(client.getQueryData(["options-chain", "NVDA", "2026-12-11"])).toBeUndefined();
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

  it("totals what it can when a holding has no live figure, and names it", async () => {
    // tastytrade sent no quote for SPY: its delta and Greeks are unknown.
    const unquoted = { ...POSITIONS.groups[1], quote: null, legs: [{ ...POSITIONS.groups[1].legs[0], quote: null }] };
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue({ ...POSITIONS, groups: [POSITIONS.groups[0], unquoted] });
    renderPage();
    const tiles = await screen.findByTestId("positions-totals");
    expect(tiles).toHaveTextContent("+$12"); // NVDA's short call: 0.12 a share a day, 100 shares
    expect(tiles).not.toHaveTextContent("—");
    expect(tiles).toHaveTextContent("leaves out SPY (no live price or delta from tastytrade)");
    expect(tiles).toHaveTextContent("leaves out SPY (no live theta from tastytrade)");
  });

  it("takes a mark of 0 as no price", async () => {
    // A halted underlying can come back marked 0: the card falls back to the report's price.
    const zero = { ...POSITIONS.groups[0], quote: { ...POSITIONS.groups[0].quote!, mark: 0 } };
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerPositions).mockResolvedValue({ ...POSITIONS, groups: [zero] });
    renderPage();
    const [nvda] = await screen.findAllByTestId("position-group");
    await waitFor(() => expect(within(nvda).getByTestId("position-greeks")).toHaveTextContent(/for a 1% rise/));
    expect(within(nvda).getByTestId("position-greeks")).not.toHaveTextContent(/: \$0 for a 1% rise/);
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
