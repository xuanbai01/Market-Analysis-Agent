import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { fetchOptionsChain } from "../../lib/options-api";
import { OptionsReportSchema } from "../../lib/options-schemas";
import { clearOwnerKey, getOwnerKey, setOwnerKey } from "../../lib/owner";
import { fetchLiveChain } from "../../lib/owner-api";
import { ExpirySection } from "./ExpirySection";
import { RAW_OPTIONS_REPORT } from "./fixture";

vi.mock("../../lib/options-api", () => ({ fetchOptionsReport: vi.fn(), fetchOptionsChain: vi.fn() }));
vi.mock("../../lib/owner-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/owner-api")>()),
  fetchLiveChain: vi.fn(),
}));

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
const CHAIN = REPORT.chain!;

function section(initial = CHAIN, listed = REPORT.listed_expiries) {
  return (
    <ExpirySection
      symbol="NVDA"
      listed={listed}
      initial={initial}
      spot={REPORT.spot}
      quotedAt={REPORT.quoted_at}
      skew25={REPORT.skew25}
    />
  );
}

function renderSection(ui = section()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (child: JSX.Element) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/options/NVDA"]}>
        <Routes>
          <Route path="/options/:ticker" element={child} />
          <Route path="/login" element={<div>sign-in page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(wrap(ui));
  return { ...view, rerender: (next: JSX.Element) => view.rerender(wrap(next)) };
}

const select = () => screen.getByTestId("options-expiry-select") as HTMLSelectElement;

afterEach(() => {
  vi.mocked(fetchOptionsChain).mockReset();
  vi.mocked(fetchLiveChain).mockReset();
  clearOwnerKey();
});

describe("ExpirySection labels", () => {
  it("names each expiry with its days and whether it is the monthly", () => {
    renderSection();
    const labels = Array.from(select().options).map((o) => o.textContent ?? "");
    expect(labels.every((l) => / · \d+ days? · (monthly|weekly)$/.test(l))).toBe(true);
    expect(labels).toContain("Dec 18, 2026 · 35 days · monthly");
  });

  it("gives open interest a sentence, and the skew only for the report's own expiry", async () => {
    vi.mocked(fetchOptionsChain).mockResolvedValue({ ...CHAIN, expiry: "2026-12-18" });
    renderSection();
    expect(screen.getByTestId("options-oi-block-summary")).toHaveTextContent(/^Most open near the money/);
    expect(screen.getByTestId("options-smile-block-summary")).toHaveTextContent(/25Δ puts are priced/);
    fireEvent.change(select(), { target: { value: "2026-12-18" } });
    await vi.waitFor(() => expect(fetchOptionsChain).toHaveBeenCalledWith("NVDA", "2026-12-18"));
    // The new chain draws with its open interest sentence, but no skew: the
    // report's skew is for its own expiry.
    expect(await screen.findByTestId("options-oi-block-summary")).toBeInTheDocument();
    expect(screen.queryByTestId("options-smile-block-summary")).toBeNull();
  });
});

describe("ExpirySection", () => {
  it("shows the default expiry's chain with the at-the-money row marked", () => {
    renderSection();
    const rows = screen.getAllByTestId("options-chain-row");
    expect(rows).toHaveLength(CHAIN.rows.length);
    const atm = rows.filter((r) => r.getAttribute("data-atm") === "true");
    expect(atm).toHaveLength(1);
    expect(within(atm[0]).getByTestId("options-chain-strike")).toHaveTextContent("165");
    expect((screen.getByTestId("options-expiry-select") as HTMLSelectElement).value).toBe(CHAIN.expiry);
  });

  it("builds strategies on the expiry shown, and starts over when it changes", async () => {
    const other = { ...CHAIN, expiry: "2026-12-18", forward: 140, rows: CHAIN.rows.map((r) => ({ ...r })) };
    vi.mocked(fetchOptionsChain).mockResolvedValue(other);
    renderSection();
    const panel = screen.getByTestId("options-strategy-panel");
    expect(within(panel).getByTestId("strategy-leg-strike")).toHaveValue("165");
    fireEvent.change(select(), { target: { value: "2026-12-18" } });
    await screen.findByText("Strategy, Dec 18, 2026 expiry");
    expect(within(screen.getByTestId("options-strategy-panel")).getByTestId("strategy-leg-strike")).toHaveValue("140");
  });

  it("dims a side with no usable quote", () => {
    const rows = CHAIN.rows.map((r, i) => (i === 0 ? { ...r, call_usable: false, call_iv: null } : r));
    renderSection(section({ ...CHAIN, rows }));
    const first = screen.getAllByTestId("options-chain-row")[0];
    expect(within(first).getByTestId("options-chain-call-iv")).toHaveTextContent("—");
  });

  it("prints a zero bid beside a real ask, and a dash only where there is no quote at all", () => {
    const rows = CHAIN.rows.map((r, i) =>
      i === 0 ? { ...r, call_bid: 0, call_ask: 0.05 } : i === 1 ? { ...r, call_bid: 0, call_ask: 0 } : r,
    );
    renderSection(section({ ...CHAIN, rows }));
    const [zeroBid, none] = screen.getAllByTestId("options-chain-row");
    expect(within(zeroBid).getAllByTestId("options-chain-call-bid")[0]).toHaveTextContent("0.00");
    expect(within(none).getAllByTestId("options-chain-call-bid")[0]).toHaveTextContent("—");
    expect(within(none).getAllByTestId("options-chain-call-ask")[0]).toHaveTextContent("—");
  });

  it("prints no ask where nobody offers, beside a real bid", () => {
    const rows = CHAIN.rows.map((r, i) => (i === 0 ? { ...r, put_bid: 0.05, put_ask: 0 } : r));
    renderSection(section({ ...CHAIN, rows }));
    const first = screen.getAllByTestId("options-chain-row")[0];
    expect(within(first).getByTestId("options-chain-put-bid")).toHaveTextContent("0.05");
    expect(within(first).getByTestId("options-chain-put-ask")).toHaveTextContent("—");
  });

  it("drops an expiry's error once the report's own chain is that expiry", async () => {
    vi.mocked(fetchOptionsChain).mockRejectedValue(new ApiError({ status: 503, title: "Option data is unavailable" }));
    const { rerender } = renderSection();
    const picked = REPORT.listed_expiries[2];
    fireEvent.change(select(), { target: { value: picked } });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    rerender(section({ ...CHAIN, expiry: picked }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("sends a stale sign-in back to the sign-in page when an expiry is read", async () => {
    vi.mocked(fetchOptionsChain).mockRejectedValue(new ApiError({ status: 401, title: "Unauthorized" }));
    renderSection();
    fireEvent.change(select(), { target: { value: REPORT.listed_expiries[2] } });
    expect(await screen.findByText("sign-in page")).toBeInTheDocument();
  });

  it("reads another expiry when one is picked", async () => {
    const other = { ...CHAIN, expiry: "2026-12-18", rows: CHAIN.rows.slice(0, 3) };
    vi.mocked(fetchOptionsChain).mockResolvedValue(other);
    renderSection();
    fireEvent.change(screen.getByTestId("options-expiry-select"), { target: { value: "2026-12-18" } });
    expect(fetchOptionsChain).toHaveBeenCalledWith("NVDA", "2026-12-18");
    expect(await screen.findAllByTestId("options-chain-row")).toHaveLength(3);
  });

  it("follows the report when a refetch moves its expiry, unless one was picked", () => {
    const { rerender } = renderSection();
    const [, next, later] = REPORT.listed_expiries;
    rerender(section({ ...CHAIN, expiry: next }));
    expect(select().value).toBe(next);
    expect(fetchOptionsChain).not.toHaveBeenCalled();

    vi.mocked(fetchOptionsChain).mockReturnValue(new Promise(() => {}));
    fireEvent.change(select(), { target: { value: later } });
    rerender(section({ ...CHAIN, expiry: REPORT.listed_expiries[3] }));
    expect(select().value).toBe(later);
  });

  it("drops a picked expiry once it is no longer listed", () => {
    vi.mocked(fetchOptionsChain).mockReturnValue(new Promise(() => {}));
    const { rerender } = renderSection();
    const picked = REPORT.listed_expiries[2];
    fireEvent.change(select(), { target: { value: picked } });
    rerender(section(CHAIN, REPORT.listed_expiries.filter((d) => d !== picked)));
    expect(select().value).toBe(CHAIN.expiry);
  });
});

describe("ExpirySection live quotes", () => {
  const LIVE = {
    symbol: "NVDA", expiry: CHAIN.expiry, spot: 163.4, quoted_at: "2026-11-16T15:00:00Z",
    updated_at: new Date(Date.now() - 3000).toISOString(), source: "tastytrade" as const,
    chain: { ...CHAIN, forward: 163.9 },
  };
  const delayedForward = `forward $${CHAIN.forward.toFixed(2)}`;

  it("offers no live switch without the owner key", () => {
    renderSection();
    expect(screen.queryByTestId("options-live-toggle")).toBeNull();
  });

  it("switches the expiry to tastytrade's live quotes and says how old they are", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockResolvedValue(LIVE);
    renderSection();
    expect(fetchLiveChain).not.toHaveBeenCalled(); // delayed until asked
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(screen.getByTestId("options-live-status")).toHaveTextContent(/Live · tastytrade · quotes \d+s old/));
    expect(fetchLiveChain).toHaveBeenCalledWith("k".repeat(40), "NVDA", CHAIN.expiry);
    expect(screen.getAllByText(/forward \$163\.90/).length).toBeGreaterThan(0); // the live chain is drawn
  });

  it("keeps the delayed chain and says why when live quotes fail", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockRejectedValue(new ApiError({ status: 503, title: "tastytrade answered 503" }));
    renderSection();
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(screen.getByTestId("options-live-status")).toHaveTextContent(/Live quotes unavailable: tastytrade answered 503/));
    expect(screen.getAllByText((text) => text.includes(delayedForward)).length).toBeGreaterThan(0);
  });

  it("falls back to the delayed chain when a later read fails", async () => {
    // The last live read isn't left on screen as if live (#130's AI review).
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"], shouldAdvanceTime: true });
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockResolvedValueOnce(LIVE).mockRejectedValue(new ApiError({ status: 503, title: "tastytrade answered 503" }));
    renderSection();
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(screen.getByTestId("options-live-status")).toHaveTextContent(/Live · tastytrade/));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16_000);
    });
    await vi.waitFor(() => expect(screen.getByTestId("options-live-status")).toHaveTextContent(/Live quotes unavailable: tastytrade answered 503/));
    expect(screen.getAllByText((text) => text.includes(delayedForward)).length).toBeGreaterThan(0);
    vi.useRealTimers();
  });

  it("keeps counting the quotes' age between reads", async () => {
    // Not frozen at "3s old" until the next read lands (#130's AI review).
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"], shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-11-16T15:00:03Z"));
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockResolvedValue({ ...LIVE, updated_at: "2026-11-16T15:00:00Z" });
    renderSection();
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(screen.getByTestId("options-live-status")).toHaveTextContent("quotes 3s old"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });
    expect(screen.getByTestId("options-live-status")).toHaveTextContent(/quotes [89]s old/);
    expect(fetchLiveChain).toHaveBeenCalledTimes(1); // the same read, older
    vi.useRealTimers();
  });

  it("signs out on a 401 from the live read", async () => {
    localStorage.setItem("market-agent.auth-token", "stale");
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockRejectedValue(new ApiError({ status: 401, title: "Sign in again." }));
    renderSection();
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(localStorage.getItem("market-agent.auth-token")).toBeNull());
  });

  it("says so when the quotes carry no time", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockResolvedValue({ ...LIVE, updated_at: null });
    renderSection();
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(screen.getByTestId("options-live-status")).toHaveTextContent("Live · tastytrade · quote time unknown · shown to you only"));
  });

  it("keeps the key when tastytrade doesn't list the expiry", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockRejectedValue(new ApiError({ status: 422, title: "tastytrade lists no NVDA options expiring 2026-12-11." }));
    renderSection();
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(screen.getByTestId("options-live-status")).toHaveTextContent(/lists no NVDA options/));
    expect(screen.getByTestId("options-live-status")).toHaveTextContent("expiring 2026-12-11. Showing the delayed chain."); // one full stop
    expect(getOwnerKey()).toBe("k".repeat(40));
  });

  it("forgets a refused owner key", async () => {
    setOwnerKey("k".repeat(40));
    vi.mocked(fetchLiveChain).mockRejectedValue(new ApiError({ status: 403, title: "This needs the owner key." }));
    renderSection();
    fireEvent.click(screen.getByTestId("options-live-toggle"));
    await vi.waitFor(() => expect(getOwnerKey()).toBeNull());
    expect(screen.queryByTestId("options-live-toggle")).toBeNull();
  });
});

