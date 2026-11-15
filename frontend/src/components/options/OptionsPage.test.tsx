import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { fetchOptionsReport } from "../../lib/options-api";
import { OptionsReportSchema } from "../../lib/options-schemas";
import { RAW_NO_OPTIONS_REPORT, RAW_OPTIONS_REPORT } from "./fixture";
import OptionsPage from "./OptionsPage";

vi.mock("../../lib/options-api", () => ({ fetchOptionsReport: vi.fn(), fetchOptionsChain: vi.fn() }));

const REPORT = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/options/nvda"]}>
        <Routes>
          <Route path="/options/:ticker" element={<OptionsPage />} />
          <Route path="/login" element={<div>sign-in page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.mocked(fetchOptionsReport).mockReset());

describe("OptionsPage", () => {
  it("shows a loading state while the chains are read", async () => {
    let release: (r: typeof REPORT) => void = () => {};
    vi.mocked(fetchOptionsReport).mockReturnValue(new Promise((resolve) => (release = resolve)));
    renderPage();
    expect(screen.getByTestId("options-loading")).toBeInTheDocument();
    release(REPORT);
    await screen.findByTestId("options-asof");
  });

  it("asks for the upper-cased ticker and draws the report", async () => {
    vi.mocked(fetchOptionsReport).mockResolvedValue(REPORT);
    renderPage();
    await screen.findByTestId("options-asof"); // the title shows before the data; this waits for it
    expect(screen.getByTestId("options-title")).toHaveTextContent("NVDA options");
    expect(fetchOptionsReport).toHaveBeenCalledWith("NVDA");
    expect(screen.getByText("NVIDIA Corporation")).toBeInTheDocument();
    expect(screen.getByTestId("options-asof")).toHaveTextContent(/last close/i);
    expect(screen.getByTestId("options-tiles")).toHaveTextContent("59.5%");
    for (const id of ["options-cone", "options-term", "options-earnings", "options-expiry-section", "options-strategy-panel"]) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
    expect(screen.getByTestId("options-disclaimer")).toHaveTextContent(/not advice/i);
    expect(screen.getByRole("link", { name: /dashboard/i })).toHaveAttribute("href", "/symbol/NVDA");
  });

  it("ranks today's IV30 once there's history, and says it's collecting before", async () => {
    vi.mocked(fetchOptionsReport).mockResolvedValue(REPORT);
    const { unmount } = renderPage();
    expect(await screen.findByTestId("options-tiles")).toHaveTextContent("IV history100thpercentile over 70 sessions");
    unmount();
    vi.mocked(fetchOptionsReport).mockResolvedValue({
      ...REPORT,
      history: { points: [], sessions: 1, since: "2026-11-13", percentile: null, rank: null },
    });
    renderPage();
    expect(await screen.findByTestId("options-tiles")).toHaveTextContent("Collecting: 1 of 63 sessions");
  });

  it("says there's nothing to rank when today has no IV30, whatever the history", async () => {
    vi.mocked(fetchOptionsReport).mockResolvedValue({
      ...REPORT,
      iv30: null,
      history: { ...REPORT.history, sessions: 70, percentile: null, rank: null },
    });
    renderPage();
    const tiles = await screen.findByTestId("options-tiles");
    expect(tiles).toHaveTextContent("No IV30 today to rank");
    expect(tiles).not.toHaveTextContent("Collecting");
  });

  it("flags an IV30 the backend had to extrapolate", async () => {
    vi.mocked(fetchOptionsReport).mockResolvedValue({ ...REPORT, iv30_extrapolated: true });
    renderPage();
    expect(await screen.findByTestId("options-tiles")).toHaveTextContent(/extrapolated/i);
  });

  it("says when the quotes are delayed prints from a session", async () => {
    vi.mocked(fetchOptionsReport).mockResolvedValue({ ...REPORT, at_close: false, quoted_at: "2026-11-16T10:45:00-05:00" });
    renderPage();
    expect(await screen.findByTestId("options-asof")).toHaveTextContent(/15 minutes delayed/i);
  });

  it("leaves out a panel whose chart has nothing to draw", async () => {
    const earnings = { ...REPORT.earnings!, past: [], implied_move: null, implied_move_usd: null, next_date: null, refused: null };
    vi.mocked(fetchOptionsReport).mockResolvedValue({ ...REPORT, expiries: REPORT.expiries.slice(0, 1), earnings });
    renderPage();
    await screen.findByTestId("options-tiles");
    for (const title of ["Expected move, one standard deviation", "Term structure: at-the-money IV", "Earnings"]) {
      expect(screen.queryByText(title)).toBeNull();
    }
    expect(screen.getByText("One expiry")).toBeInTheDocument();
  });

  it("says when a symbol lists no options", async () => {
    vi.mocked(fetchOptionsReport).mockResolvedValue(OptionsReportSchema.parse(RAW_NO_OPTIONS_REPORT));
    renderPage();
    expect(await screen.findByTestId("options-empty")).toHaveTextContent("NVDA lists no options");
    expect(screen.queryByTestId("options-cone")).toBeNull();
  });

  it("says when nothing can be priced", async () => {
    vi.mocked(fetchOptionsReport).mockResolvedValue({ ...REPORT, status: "no_usable_quotes", expiries: [], chain: null });
    renderPage();
    expect(await screen.findByTestId("options-empty")).toHaveTextContent(/no two-sided quotes/i);
  });

  it("sends a stale sign-in back to the sign-in page", async () => {
    vi.mocked(fetchOptionsReport).mockRejectedValue(new ApiError({ status: 401, title: "Unauthorized" }));
    renderPage();
    expect(await screen.findByText("sign-in page")).toBeInTheDocument();
  });

  it("shows the error when the data is unavailable", async () => {
    vi.mocked(fetchOptionsReport).mockRejectedValue(new ApiError({ status: 503, title: "Option data is unavailable" }));
    renderPage();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
