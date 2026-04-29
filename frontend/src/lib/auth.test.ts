/**
 * Smoke tests for the localStorage auth helpers. Keeps the storage-key
 * decision documented and locks in the failure mode of "localStorage
 * is unavailable" (private mode Safari, etc).
 */
import { describe, it, expect } from "vitest";
import {
  clearStoredToken,
  getStoredToken,
  setStoredToken,
} from "./auth";

// localStorage is reset between tests by ``test-setup.ts`` via the
// Map-backed Storage polyfill (happy-dom + Node 25 ships an empty
// ``window.localStorage``).

describe("auth helpers", () => {
  it("returns null when nothing is stored", () => {
    expect(getStoredToken()).toBeNull();
  });

  it("round-trips a token", () => {
    setStoredToken("the-secret");
    expect(getStoredToken()).toBe("the-secret");
  });

  it("clears the token", () => {
    setStoredToken("the-secret");
    clearStoredToken();
    expect(getStoredToken()).toBeNull();
  });

  it("does not throw when localStorage throws", () => {
    const original = window.localStorage.getItem.bind(window.localStorage);
    window.localStorage.getItem = () => {
      throw new Error("boom");
    };
    try {
      expect(getStoredToken()).toBeNull();
    } finally {
      window.localStorage.getItem = original;
    }
  });
});
