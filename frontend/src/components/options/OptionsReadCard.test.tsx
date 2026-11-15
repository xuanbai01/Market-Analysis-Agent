import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { fetchOptionsRead } from "../../lib/options-api";
import { OptionsReadSchema } from "../../lib/options-schemas";
import { RAW_OPTIONS_READ } from "./fixture";
import { OptionsReadCard } from "./OptionsReadCard";

vi.mock("../../lib/options-api", () => ({ fetchOptionsRead: vi.fn() }));

const READ = OptionsReadSchema.parse(RAW_OPTIONS_READ);

function renderCard(quotedAt = READ.quoted_at) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/options/NVDA"]}>
        <Routes>
          <Route path="/options/:ticker" element={<OptionsReadCard symbol="NVDA" quotedAt={quotedAt} />} />
          <Route path="/login" element={<div>sign-in page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.mocked(fetchOptionsRead).mockReset());

describe("OptionsReadCard", () => {
  it("says it's writing while the read is on its way", () => {
    vi.mocked(fetchOptionsRead).mockReturnValue(new Promise(() => {}));
    renderCard();
    expect(screen.getByTestId("options-read-loading")).toBeInTheDocument();
  });

  it("shows the headline and each point with the figures it cites", async () => {
    vi.mocked(fetchOptionsRead).mockResolvedValue(READ);
    renderCard();
    expect(await screen.findByText(READ.headline)).toBeInTheDocument();
    const chips = screen.getAllByTestId("options-read-evidence");
    expect(chips).toHaveLength(4);
    expect(chips[0]).toHaveTextContent("59.46%");
    expect(screen.getByTestId("options-read")).toHaveTextContent(/AI-written/i);
    expect(screen.getByTestId("options-read")).toHaveTextContent(/not advice/i);
  });

  it("says which quotes it read when the page has moved on", async () => {
    vi.mocked(fetchOptionsRead).mockResolvedValue(READ);
    renderCard("2026-11-16T10:45:00-05:00");
    expect(await screen.findByTestId("options-read-stale")).toHaveTextContent(/Nov 13/);
  });

  it("is quiet when there's nothing to read", async () => {
    vi.mocked(fetchOptionsRead).mockRejectedValue(new ApiError({ status: 404, title: "No priced options" }));
    const { container } = renderCard();
    await vi.waitFor(() => expect(fetchOptionsRead).toHaveBeenCalled());
    await vi.waitFor(() => expect(container.querySelector("[data-testid=options-read-loading]")).toBeNull());
    expect(screen.queryByTestId("options-read")).toBeNull();
  });

  it("says when the read limit is reached, and when no read could be written", async () => {
    vi.mocked(fetchOptionsRead).mockRejectedValue(new ApiError({ status: 429, title: "Too many", retryAfterSeconds: 600 }));
    const { unmount } = renderCard();
    expect(await screen.findByTestId("options-read-unavailable")).toHaveTextContent(/10 minutes/);
    unmount();
    vi.mocked(fetchOptionsRead).mockRejectedValue(new ApiError({ status: 503, title: "No read" }));
    renderCard();
    expect(await screen.findByTestId("options-read-unavailable")).toHaveTextContent(/no read/i);
  });

  it("sends a stale sign-in back to the sign-in page", async () => {
    vi.mocked(fetchOptionsRead).mockRejectedValue(new ApiError({ status: 401, title: "Unauthorized" }));
    renderCard();
    expect(await screen.findByText("sign-in page")).toBeInTheDocument();
  });
});
