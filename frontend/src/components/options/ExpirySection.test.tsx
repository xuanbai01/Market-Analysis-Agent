import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { fetchOptionsChain } from "../../lib/options-api";
import { OptionsReportSchema } from "../../lib/options-schemas";
import { ExpirySection } from "./ExpirySection";
import { RAW_OPTIONS_REPORT } from "./fixture";

vi.mock("../../lib/options-api", () => ({ fetchOptionsReport: vi.fn(), fetchOptionsChain: vi.fn() }));

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
const CHAIN = REPORT.chain!;

function section(initial = CHAIN, listed = REPORT.listed_expiries) {
  return <ExpirySection symbol="NVDA" listed={listed} initial={initial} spot={REPORT.spot} />;
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

afterEach(() => vi.mocked(fetchOptionsChain).mockReset());

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
