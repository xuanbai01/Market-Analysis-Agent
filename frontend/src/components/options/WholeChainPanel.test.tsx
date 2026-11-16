import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { OptionsReportSchema } from "../../lib/options-schemas";
import { clearOwnerKey, getOwnerKey, setOwnerKey } from "../../lib/owner";
import { fetchWholeChain } from "../../lib/owner-api";
import { type WholeChain, WholeChainSchema } from "../../lib/owner-schemas";
import { RAW_OPTIONS_REPORT } from "./fixture";
import { WholeChainPanel } from "./WholeChainPanel";

vi.mock("../../lib/owner-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/owner-api")>()),
  fetchWholeChain: vi.fn(),
}));

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
const WHOLE: WholeChain = WholeChainSchema.parse({
  symbol: "NVDA",
  spot: REPORT.spot,
  quoted_at: "2026-11-16T15:00:00Z",
  as_of: "2026-11-16T15:00:01Z",
  expiries: REPORT.expiries,
  positioning: {
    call_open_interest: 120_000, put_open_interest: 150_000, put_call: 1.25, top: [], max_pain: null,
    exposure: [{ strike: 180, gex: 5_000_000, dex: 1_000_000 }, { strike: 170, gex: -3_000_000, dex: -800_000 }],
    call_gex: 9e6, put_gex: -6e6, net_gex: 3e6, call_dex: 2e6, put_dex: -1e6, net_dex: 1e6,
    call_wall: 180, put_wall: 170, gamma_flip: 175, assumption: "Gamma exposure assumes dealers…",
  },
  max_days: 120,
  strike_range: 0.15,
  options_read: 1000,
  options_quoted: 990,
  left_out: [],
  capped: false,
  source: "tastytrade",
});

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/options/NVDA"]}>
        <Routes>
          <Route path="/options/:ticker" element={<WholeChainPanel symbol="NVDA" />} />
          <Route path="/login" element={<div>sign-in page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.mocked(fetchWholeChain).mockReset();
  clearOwnerKey();
});

describe("WholeChainPanel", () => {
  it("shows nothing without the owner key", () => {
    renderPanel();
    expect(screen.queryByTestId("options-whole-chain-panel")).toBeNull();
  });

  it("asks tastytrade only when the button is pressed", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchWholeChain).mockResolvedValue(WHOLE);
    renderPanel();
    expect(screen.getByTestId("options-whole-chain-panel")).toBeInTheDocument();
    expect(fetchWholeChain).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("options-whole-chain-read"));
    expect(await screen.findByTestId("options-whole-chain-panel-summary")).toHaveTextContent(/^Every expiry to /);
    expect(fetchWholeChain).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("options-whole-chain-source")).toHaveTextContent(/990\s+contracts · shown to you only, never stored/);
    expect(screen.getByTestId("options-whole-chain-read")).toHaveTextContent("Read again");
  });

  it("names what the read left out", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchWholeChain).mockResolvedValue({ ...WHOLE, left_out: ["2026-12-26"], capped: true });
    renderPanel();
    fireEvent.click(screen.getByTestId("options-whole-chain-read"));
    expect(await screen.findByText("No usable quotes for Dec 26: left out.")).toBeInTheDocument();
    expect(screen.getByText(/the farthest expiries are left out/)).toBeInTheDocument();
  });

  it("says when tastytrade lists no options, and keeps the key", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchWholeChain).mockRejectedValue(new ApiError({ status: 422, title: "tastytrade lists no options on NVDA to read." }));
    renderPanel();
    fireEvent.click(screen.getByTestId("options-whole-chain-read"));
    expect(await screen.findByText("tastytrade lists no options on NVDA to read.")).toBeInTheDocument();
    expect(getOwnerKey()).not.toBeNull();
  });

  it("gives the reason when the feed fails", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchWholeChain).mockRejectedValue(new ApiError({ status: 503, title: "tastytrade's feed failed: timed out" }));
    renderPanel();
    fireEvent.click(screen.getByTestId("options-whole-chain-read"));
    expect(await screen.findByText(/The whole chain is unavailable: tastytrade's feed failed: timed out/)).toBeInTheDocument();
  });

  it("forgets a key the server refuses", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchWholeChain).mockRejectedValue(new ApiError({ status: 403, title: "Forbidden" }));
    renderPanel();
    fireEvent.click(screen.getByTestId("options-whole-chain-read"));
    await waitFor(() => expect(getOwnerKey()).toBeNull());
  });
});
