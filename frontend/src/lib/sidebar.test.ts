import { describe, expect, it } from "vitest";

import {
  comparePair,
  compareHref,
  pairFromSearch,
  readSidebarCollapsed,
  searchShortcutLabel,
  sidebarRecent,
  SIDEBAR_RECENT_MAX,
  writeSidebarCollapsed,
} from "./sidebar";

describe("comparePair", () => {
  it("compares the ticker on screen with the most recent other one", () => {
    expect(comparePair("KO", ["KO", "JPM", "NVDA"], [])).toEqual({ a: "KO", b: "JPM" });
  });

  it("starts from the most recent ticker off a symbol page", () => {
    expect(comparePair(null, ["JPM", "NVDA"], ["KO"])).toEqual({ a: "JPM", b: "NVDA" });
  });

  it("falls back to the watchlist, then popular names", () => {
    expect(comparePair(null, [], ["KO"])).toEqual({ a: "KO", b: "NVDA" });
    expect(comparePair("NVDA", [], [])).toEqual({ a: "NVDA", b: "AAPL" });
  });

  it("always yields two distinct names for a fresh user", () => {
    const { a, b } = comparePair(null, [], []);
    expect(a).toBeTruthy();
    expect(b).toBeTruthy();
    expect(a).not.toBe(b);
  });
});

describe("compareHref / pairFromSearch", () => {
  it("round-trips a pair through the compare URL", () => {
    const href = compareHref({ a: "AAPL", b: "MSFT" });
    expect(href).toBe("/compare?a=AAPL&b=MSFT");
    expect(pairFromSearch(href.slice(href.indexOf("?")))).toEqual({ a: "AAPL", b: "MSFT" });
  });

  it("uppercases and requires both params", () => {
    expect(pairFromSearch("?a=aapl&b=msft")).toEqual({ a: "AAPL", b: "MSFT" });
    expect(pairFromSearch("?a=AAPL")).toBeNull();
    expect(pairFromSearch("")).toBeNull();
  });
});

describe("sidebarRecent", () => {
  it("skips tickers already in the watchlist", () => {
    expect(sidebarRecent(["NVDA", "KO", "JPM"], ["KO"])).toEqual(["NVDA", "JPM"]);
  });

  it("caps the rows", () => {
    const many = Array.from({ length: 10 }, (_, i) => `T${i}`);
    expect(sidebarRecent(many, [])).toHaveLength(SIDEBAR_RECENT_MAX);
    expect(sidebarRecent(many, [])[0]).toBe("T0");
  });
});

describe("collapsed preference", () => {
  it("defaults to expanded and persists a choice", () => {
    expect(readSidebarCollapsed()).toBe(false);
    writeSidebarCollapsed(true);
    expect(readSidebarCollapsed()).toBe(true);
    writeSidebarCollapsed(false);
    expect(readSidebarCollapsed()).toBe(false);
  });
});

describe("searchShortcutLabel", () => {
  it("uses ⌘K on Apple platforms and Ctrl K elsewhere", () => {
    expect(searchShortcutLabel("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")).toBe("⌘K");
    expect(searchShortcutLabel("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("Ctrl K");
  });
});
