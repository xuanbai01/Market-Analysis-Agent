import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { LensPage } from "./LensPage";
import { LENS } from "./fixture";
import { fetchLens } from "../../lib/api";

vi.mock("../../lib/api", () => ({ fetchLens: vi.fn() }));
const fetchMock = vi.mocked(fetchLens);

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/lens/megacap-capex"]}>
        <Routes>
          <Route path="/lens/:id" element={<LensPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => fetchMock.mockReset());

describe("LensPage", () => {
  it("asks for the lens in the URL and explains the first-load wait", async () => {
    // Resolved before the test ends: a fetch left pending hung the next test.
    let release: (report: typeof LENS) => void = () => {};
    fetchMock.mockReturnValue(new Promise((resolve) => (release = resolve)));
    renderPage();
    expect(fetchMock).toHaveBeenCalledWith("megacap-capex");
    expect(screen.getByTestId("lens-loading")).toHaveTextContent(/about 20 seconds/);
    release(LENS);
    await screen.findByTestId("lens-distribution");
  });

  it("leads with the AI read, each point showing the figures it cites", async () => {
    fetchMock.mockResolvedValue(LENS);
    renderPage();
    const narrative = await screen.findByTestId("lens-narrative");
    expect(narrative).toHaveTextContent("Spending is concentrated in one heavy investor.");
    expect(within(narrative).getByTestId("lens-evidence")).toHaveTextContent("25.00%");
  });

  it("shows both charts, the latest-year table ranked by intensity, and the method", async () => {
    fetchMock.mockResolvedValue(LENS);
    renderPage();
    await screen.findByTestId("lens-distribution");
    expect(screen.getByTestId("lens-bars")).toBeInTheDocument();
    const rows = screen.getAllByTestId("lens-row");
    expect(rows.map((r) => r.textContent?.slice(0, 3))).toEqual(["AAA", "CCC", "BBB"]);
    expect(rows[0]).toHaveTextContent("$40.0B");
    expect(rows[0]).toHaveTextContent("25.0%");
    expect(rows[0]).toHaveTextContent("▲ 5.0 pts since CY2023");
    expect(rows[2]).toHaveTextContent("—"); // negative operating cash flow: no ratio
    expect(screen.getByTestId("lens-method")).toHaveTextContent("SEC XBRL");
  });

  it("still renders the data when the AI read is missing", async () => {
    fetchMock.mockResolvedValue({ ...LENS, narrative: null });
    renderPage();
    await screen.findByTestId("lens-distribution");
    expect(screen.queryByTestId("lens-narrative")).toBeNull();
  });
});
