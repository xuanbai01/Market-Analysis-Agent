import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { clearOwnerKey, getOwnerKey, setOwnerKey } from "../../lib/owner";
import { fetchOwnerTrades, fetchOwnerTradesCsv } from "../../lib/owner-api";
import { type OwnerTrades, OwnerTradesSchema } from "../../lib/owner-schemas";
import TradesPage from "./TradesPage";

vi.mock("../../lib/owner-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/owner-api")>()),
  fetchOwnerTrades: vi.fn(),
  fetchOwnerTradesCsv: vi.fn(),
}));

const TRADES: OwnerTrades = OwnerTradesSchema.parse({
  synced: true,
  trades: [
    { id: 3, account: 1, executed_at: "2026-11-13T15:30:00Z", action: "Buy to Close", symbol: "NVDA  261218C00175000", underlying: "NVDA", quantity: 1, price: 1.2, fees: 1.1, net_value: -121.1 },
    { id: 2, account: 1, executed_at: "2026-10-01T15:30:00Z", action: "Sell to Open", symbol: "NVDA  261218C00175000", underlying: "NVDA", quantity: 1, price: 4.8, fees: 1.14, net_value: 478.86 },
    { id: 1, account: 1, executed_at: "2026-09-01T15:30:00Z", action: "Buy to Open", symbol: "SPY   261218P00640000", underlying: "SPY", quantity: 2, price: 6.1, fees: 2.2, net_value: -1222.2 },
  ],
  journal: {
    positions: [
      {
        id: "order-1", account: 1, underlying: "SPY", structure: "long put", status: "open", opened_at: "2026-09-01T15:30:00+00:00",
        legs: [{ symbol: "SPY   261218P00640000", kind: "put", expiry: "2026-12-18", strike: 640, quantity: 2, closed: 0 }],
        open_cash: -1222.2, fees: 2.2, transactions: [1],
      },
      {
        id: "order-2", account: 1, underlying: "NVDA", structure: "short call", status: "closed", ended_by: "closed",
        opened_at: "2026-10-01T15:30:00+00:00", closed_at: "2026-11-13T15:30:00+00:00", days_held: 43,
        legs: [{ symbol: "NVDA  261218C00175000", kind: "call", expiry: "2026-12-18", strike: 175, quantity: -1, closed: 1 }],
        open_cash: 478.86, close_cash: -121.1, fees: 2.24, realized: 357.76, transactions: [2, 3],
      },
    ],
    months: [{ month: "2026-11", realized: 357.76 }],
    underlyings: [{ underlying: "NVDA", realized: 357.76 }],
    totals: { realized: 357.76, closed: 1, profitable: 1, average_days: 43, fees: 2.24 }, // the closed position's own
    unmatched: [{ id: 99, date: "2026-08-01", symbol: "NVDA", reason: "nothing open to close: it may come from before the copy starts" }],
  },
});

/** The transactions table sits on its own tab; the journal opens first. */
async function showTransactions() {
  fireEvent.click(await screen.findByTestId("trades-tab-transactions"));
  return screen.getByTestId("trades-table");
}

let client: QueryClient;

function renderPage() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TradesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  clearOwnerKey();
  vi.mocked(fetchOwnerTrades).mockReset();
  vi.mocked(fetchOwnerTradesCsv).mockReset();
});

describe("TradesPage", () => {
  it("asks for the owner key first", () => {
    renderPage();
    expect(screen.getByTestId("owner-unlock")).toBeInTheDocument();
    expect(fetchOwnerTrades).not.toHaveBeenCalled();
  });

  it("lists the trades newest first, signed, and filters by underlying", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    renderPage();
    const table = await showTransactions();
    const rows = table.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Buy to Close");
    expect(rows[0]).toHaveTextContent("−$121.10"); // to the cent, like the fees beside it
    expect(rows[1]).toHaveTextContent("+$478.86");
    expect(screen.getByTestId("trades-status")).toHaveTextContent("3 trades · a copy stored encrypted");
    fireEvent.change(screen.getByTestId("trades-underlying-filter"), { target: { value: "SPY" } });
    expect(table.querySelectorAll("tbody tr")).toHaveLength(1);
  });

  it("opens on the journal: what closed, the months, the positions", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    renderPage();
    expect(await screen.findByTestId("journal-summary")).toHaveTextContent(
      "1 position closed, 1 at a profit (100%), held 43 days on average. Realized: +$358 after $2 in fees.",
    );
    expect(screen.getAllByTestId("realized-bar")).toHaveLength(1);
    const rows = screen.getAllByTestId("journal-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("NVDA"); // newest opened first
    expect(rows[0]).toHaveTextContent("short call");
    expect(rows[0]).toHaveTextContent("closed");
    expect(rows[0]).toHaveTextContent("43 days");
    expect(rows[0]).toHaveTextContent("+$357.76");
    expect(rows[1]).toHaveTextContent("open");
    expect(screen.queryByTestId("trades-table")).toBeNull();
  });

  it("opens a position to its legs and the fills behind it", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    renderPage();
    const [nvda] = await screen.findAllByTestId("journal-row");
    fireEvent.click(within(nvda).getByRole("button", { name: /NVDA short call/ }));
    const detail = screen.getByTestId("journal-detail");
    expect(detail).toHaveTextContent("1 short Dec 18 $175 call");
    expect(detail).toHaveTextContent("Sell to Open");
    expect(detail).toHaveTextContent("Buy to Close");
  });

  it("filters the journal by open or closed, and by underlying", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    renderPage();
    await screen.findAllByTestId("journal-row");
    fireEvent.change(screen.getByTestId("journal-status-filter"), { target: { value: "open" } });
    expect(screen.getAllByTestId("journal-row")).toHaveLength(1);
    expect(screen.getByTestId("journal-row")).toHaveTextContent("SPY");
    fireEvent.change(screen.getByTestId("journal-status-filter"), { target: { value: "all" } });
    fireEvent.change(screen.getByTestId("trades-underlying-filter"), { target: { value: "NVDA" } });
    expect(screen.getAllByTestId("journal-row")).toHaveLength(1);
    expect(screen.getByTestId("journal-row")).toHaveTextContent("NVDA");
  });

  it("names what couldn't be matched", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    renderPage();
    const note = await screen.findByTestId("journal-unmatched");
    expect(note).toHaveTextContent("1 transaction isn't in the journal");
    expect(note).toHaveTextContent("nothing open to close");
  });

  it("shows a fractional quantity as it is, as the CSV does", async () => {
    setOwnerKey("k".repeat(40));
    const half = { ...TRADES.trades[2], id: 9, symbol: "SPY", quantity: 0.5 };
    vi.mocked(fetchOwnerTrades).mockResolvedValue({ ...TRADES, trades: [half] });
    renderPage();
    const table = await showTransactions();
    expect(table.querySelector("tbody tr")).toHaveTextContent(/SPY\s*0\.5/);
  });

  it("says when the copy couldn't be updated, and why", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue({ ...TRADES, synced: false, reason: "tastytrade answered 503" });
    renderPage();
    expect(await screen.findByTestId("trades-status")).toHaveTextContent("not updated this visit: tastytrade answered 503");
  });

  it("says the copy needs its key when the server has none", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockRejectedValue(new ApiError({ status: 503, title: "the trade copy's key isn't set on the server" }));
    renderPage();
    expect(await screen.findByTestId("trades-no-vault")).toHaveTextContent("OWNER_VAULT_KEY");
  });

  it("gives the server's reason when the copy doesn't open", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockRejectedValue(new ApiError({ status: 503, title: "a stored trade doesn't open with this key" }));
    renderPage();
    expect(await screen.findByTestId("trades-vault-error")).toHaveTextContent("doesn't open with this key");
    expect(screen.queryByTestId("trades-no-vault")).toBeNull();
  });

  it("forgets a refused key, and the trades with it", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockRejectedValue(new ApiError({ status: 403, title: "This needs the owner key." }));
    renderPage();
    expect(await screen.findByTestId("owner-unlock")).toBeInTheDocument();
    expect(getOwnerKey()).toBeNull();
    await waitFor(() => expect(client.getQueryData(["owner-trades"])).toBeUndefined());
  });

  it("signs out on a 401 from the download, as the list does", async () => {
    localStorage.setItem("market-agent.auth-token", "stale");
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    vi.mocked(fetchOwnerTradesCsv).mockRejectedValue(new ApiError({ status: 401, title: "Sign in again." }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Download CSV" }));
    await waitFor(() => expect(localStorage.getItem("market-agent.auth-token")).toBeNull());
    expect(getOwnerKey()).toBeNull(); // signing out clears the owner key too
  });

  it("forgets a key the download is refused with", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    vi.mocked(fetchOwnerTradesCsv).mockRejectedValue(new ApiError({ status: 403, title: "This needs the owner key." }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Download CSV" }));
    expect(await screen.findByTestId("owner-unlock")).toBeInTheDocument();
    expect(getOwnerKey()).toBeNull();
  });

  it("doesn't call an unreachable copy empty", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(OwnerTradesSchema.parse({ trades: [], synced: false, reason: "tastytrade didn't answer" }));
    renderPage();
    expect(await screen.findByTestId("trades-empty")).toHaveTextContent("Nothing is stored yet, and tastytrade couldn't be read this visit.");
  });

  it("downloads the CSV with the owner key", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchOwnerTrades).mockResolvedValue(TRADES);
    vi.mocked(fetchOwnerTradesCsv).mockResolvedValue(new Blob(["id\n"], { type: "text/csv" }));
    const created = vi.fn(() => "blob:x");
    const revoked = vi.fn();
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked });
    // The link is clicked while in the page: some browsers ignore a detached one.
    const attached: boolean[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      attached.push(document.body.contains(this));
    });
    renderPage();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(await screen.findByRole("button", { name: "Download CSV" }));
    await waitFor(() => expect(created).toHaveBeenCalled());
    expect(attached).toEqual([true]);
    expect(document.querySelector('a[download="trades.csv"]')).toBeNull(); // and taken out after
    click.mockRestore();
    expect(revoked).not.toHaveBeenCalled(); // not at once: Safari would cancel the save
    vi.advanceTimersByTime(1000);
    expect(revoked).toHaveBeenCalledWith("blob:x");
    vi.useRealTimers();
    expect(fetchOwnerTradesCsv).toHaveBeenCalledWith("k".repeat(40));
  });
});
