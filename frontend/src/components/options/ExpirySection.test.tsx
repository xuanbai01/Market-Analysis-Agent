import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchOptionsChain } from "../../lib/options-api";
import { OptionsReportSchema } from "../../lib/options-schemas";
import { ExpirySection } from "./ExpirySection";
import { RAW_OPTIONS_REPORT } from "./fixture";

vi.mock("../../lib/options-api", () => ({ fetchOptionsReport: vi.fn(), fetchOptionsChain: vi.fn() }));

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
const CHAIN = REPORT.chain!;

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExpirySection symbol="NVDA" listed={REPORT.listed_expiries} initial={CHAIN} spot={REPORT.spot} />
    </QueryClientProvider>,
  );
}

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
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ExpirySection symbol="NVDA" listed={REPORT.listed_expiries} initial={{ ...CHAIN, rows }} spot={REPORT.spot} />
      </QueryClientProvider>,
    );
    const first = screen.getAllByTestId("options-chain-row")[0];
    expect(within(first).getByTestId("options-chain-call-iv")).toHaveTextContent("—");
  });

  it("reads another expiry when one is picked", async () => {
    const other = { ...CHAIN, expiry: "2026-12-18", rows: CHAIN.rows.slice(0, 3) };
    vi.mocked(fetchOptionsChain).mockResolvedValue(other);
    renderSection();
    fireEvent.change(screen.getByTestId("options-expiry-select"), { target: { value: "2026-12-18" } });
    expect(fetchOptionsChain).toHaveBeenCalledWith("NVDA", "2026-12-18");
    expect(await screen.findAllByTestId("options-chain-row")).toHaveLength(3);
  });
});
