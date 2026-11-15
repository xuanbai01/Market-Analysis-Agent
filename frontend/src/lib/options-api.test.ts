import { afterEach, describe, expect, it, vi } from "vitest";

import { RAW_OPTIONS_REPORT } from "../components/options/fixture";
import { ApiError } from "./api";
import { setStoredToken } from "./auth";
import { fetchOptionsChain, fetchOptionsReport } from "./options-api";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("options api", () => {
  it("fetches and parses a report with the stored token", async () => {
    setStoredToken("secret");
    const fetchMock = respond(200, RAW_OPTIONS_REPORT);
    vi.stubGlobal("fetch", fetchMock);
    const report = await fetchOptionsReport("nvda");
    expect(report.symbol).toBe("NVDA");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/v1\/options\/NVDA$/);
    expect((init as RequestInit).headers).toMatchObject({ Authorization: "Bearer secret" });
  });

  it("fetches one expiry's chain", async () => {
    const fetchMock = respond(200, RAW_OPTIONS_REPORT.chain);
    vi.stubGlobal("fetch", fetchMock);
    const chain = await fetchOptionsChain("NVDA", "2026-12-18");
    expect(chain.expiry).toBe(RAW_OPTIONS_REPORT.chain.expiry);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/v1\/options\/NVDA\/chain\/2026-12-18$/);
  });

  it("turns a 404 into an ApiError with the server's message", async () => {
    vi.stubGlobal("fetch", respond(404, { title: "No such symbol: ZZZZQ." }));
    await expect(fetchOptionsReport("ZZZZQ")).rejects.toMatchObject({ status: 404, title: "No such symbol: ZZZZQ." });
  });

  it("keeps Retry-After on a 429", async () => {
    vi.stubGlobal("fetch", respond(429, { title: "Too many option lookups" }, { "Retry-After": "120" }));
    const error = await fetchOptionsReport("SPY").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).retryAfterSeconds).toBe(120);
  });
});
