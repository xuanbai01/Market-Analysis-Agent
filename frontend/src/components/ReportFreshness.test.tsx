import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ReportFreshness } from "./ReportFreshness";
import { ApiError, fetchResearchReport } from "../lib/api";
import type { ResearchReport } from "../lib/schemas";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  fetchResearchReport: vi.fn(),
}));
const fetchMock = vi.mocked(fetchResearchReport);

const NOW = Date.parse("2026-11-08T18:00:00Z");
const FRESH = { symbol: "AAPL", generated_at: "2026-11-08T17:59:00Z" } as unknown as ResearchReport;

function renderFreshness(generatedAt = "2026-11-06T18:00:00Z") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReportFreshness ticker="AAPL" generatedAt={generatedAt} />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  fetchMock.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("ReportFreshness", () => {
  it("says how old the report is", () => {
    renderFreshness();
    expect(screen.getByTestId("report-freshness")).toHaveTextContent("Generated 2 days ago");
  });

  it("regenerates with refresh=true and swaps the new report into the page's cache", async () => {
    let resolve: (r: ResearchReport) => void = () => {};
    fetchMock.mockReturnValue(new Promise((r) => (resolve = r)));
    const client = renderFreshness();

    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    const busy = await screen.findByRole("button", { name: /Regenerating/ });
    expect(busy).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledWith("AAPL", { focus: "full", refresh: true });

    resolve(FRESH);
    await screen.findByRole("button", { name: "Regenerate" });
    expect(client.getQueryData(["report", "AAPL", "full"])).toBe(FRESH);
  });

  it("explains a rate-limit refusal with the wait", async () => {
    fetchMock.mockRejectedValue(new ApiError({ status: 429, title: "Too Many Requests", retryAfterSeconds: 600 }));
    renderFreshness();
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't regenerate: rate limit reached, try again in 10 min.",
    );
  });
});
