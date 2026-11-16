import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { clearOwnerKey, getOwnerKey, setOwnerKey } from "../../lib/owner";
import { fetchIvHistory } from "../../lib/owner-api";
import { type IvHistory, IvHistorySchema } from "../../lib/owner-schemas";
import { IvHistoryPanel } from "./IvHistoryPanel";

vi.mock("../../lib/owner-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/owner-api")>()),
  fetchIvHistory: vi.fn(),
}));

const HISTORY: IvHistory = IvHistorySchema.parse({
  symbol: "NVDA",
  as_of: "2026-11-16T15:00:00Z",
  metrics: { iv_index: 0.412, iv30: 0.415, iv_rank: 0.62, iv_percentile: 0.71, hv30: 0.352, hv60: 0.38, hv90: 0.401 },
  points: Array.from({ length: 900 }, (_, i) => ({
    date: new Date(Date.UTC(2023, 0, 2) + i * 86_400_000).toISOString().slice(0, 10),
    close: 100 + i / 10,
    iv: 0.3 + (i % 50) / 1000,
    rv20: i < 20 ? null : 0.28,
  })),
  year: { sessions: 252, iv_low: 0.3, iv_high: 0.349, iv_median: 0.325, iv_rank: 0.4, iv_percentile: 0.41 },
  iv_since: "2023-01-02",
  complete: true,
  source: "tastytrade",
});

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/options/NVDA"]}>
        <Routes>
          <Route path="/options/:ticker" element={<IvHistoryPanel symbol="NVDA" />} />
          <Route path="/login" element={<div>sign-in page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.mocked(fetchIvHistory).mockReset();
  clearOwnerKey();
});

describe("IvHistoryPanel", () => {
  it("shows nothing and asks nothing without the owner key", () => {
    renderPanel();
    expect(screen.queryByTestId("options-iv-history-panel")).toBeNull();
    expect(fetchIvHistory).not.toHaveBeenCalled();
  });

  it("draws IV and realized volatility, says where today sits, and labels the source", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchIvHistory).mockResolvedValue(HISTORY);
    renderPanel();
    expect(await screen.findByTestId("options-iv-history-panel-summary")).toHaveTextContent(
      "higher than on 41% of the past year's sessions",
    );
    expect(screen.getByTestId("options-iv-history-panel-stats")).toHaveTextContent("IV rank (tastytrade)62%");
    expect(screen.getByTestId("options-iv-history-source")).toHaveTextContent(/Live · tastytrade · read .* · shown to you only, never stored/);
    expect(screen.getByRole("img", { name: /IV and 20-session realized volatility, 252 sessions/ })).toBeInTheDocument();
  });

  it("switches between a year, three years and everything", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchIvHistory).mockResolvedValue(HISTORY);
    renderPanel();
    await screen.findByTestId("options-iv-history-panel-summary");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByRole("img", { name: /900 sessions/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });

  it("says when tastytrade has no history for the symbol, and keeps the key", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchIvHistory).mockRejectedValue(new ApiError({ status: 422, title: "tastytrade has no IV history for NVDA." }));
    renderPanel();
    expect(await screen.findByText("tastytrade has no IV history for NVDA.")).toBeInTheDocument();
    expect(getOwnerKey()).not.toBeNull();
  });

  it("gives the reason when tastytrade fails", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchIvHistory).mockRejectedValue(new ApiError({ status: 503, title: "tastytrade answered 503" }));
    renderPanel();
    expect(await screen.findByText(/IV history unavailable: tastytrade answered 503/)).toBeInTheDocument();
  });

  it("forgets a key the server refuses", async () => {
    setOwnerKey("o".repeat(40));
    vi.mocked(fetchIvHistory).mockRejectedValue(new ApiError({ status: 403, title: "Forbidden" }));
    renderPanel();
    await waitFor(() => expect(getOwnerKey()).toBeNull());
  });
});
