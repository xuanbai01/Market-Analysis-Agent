import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { readStoredList, useStoredList, writeStoredList } from "./stored-list";

const KEY = "market-agent.test-list";

describe("stored-list", () => {
  it("round-trips a list", () => {
    writeStoredList(KEY, ["NVDA", "KO"]);
    expect(readStoredList(KEY)).toEqual(["NVDA", "KO"]);
  });

  it("reads missing, corrupt or non-array payloads as empty", () => {
    expect(readStoredList(KEY)).toEqual([]);
    window.localStorage.setItem(KEY, "{not json");
    expect(readStoredList(KEY)).toEqual([]);
    window.localStorage.setItem(KEY, JSON.stringify({ a: 1 }));
    expect(readStoredList(KEY)).toEqual([]);
    window.localStorage.setItem(KEY, JSON.stringify(["NVDA", 3, null]));
    expect(readStoredList(KEY)).toEqual(["NVDA"]);
  });

  it("re-renders hook readers on every write", () => {
    const { result } = renderHook(() => useStoredList(KEY));
    expect(result.current).toEqual([]);
    act(() => writeStoredList(KEY, ["JPM"]));
    expect(result.current).toEqual(["JPM"]);
    act(() => writeStoredList(KEY, []));
    expect(result.current).toEqual([]);
  });

  it("keeps the same array while the stored value is unchanged", () => {
    writeStoredList(KEY, ["JPM"]);
    const { result, rerender } = renderHook(() => useStoredList(KEY));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("picks up writes from another tab via the storage event", () => {
    const { result } = renderHook(() => useStoredList(KEY));
    act(() => {
      window.localStorage.setItem(KEY, JSON.stringify(["KO"]));
      window.dispatchEvent(new Event("storage"));
    });
    expect(result.current).toEqual(["KO"]);
  });
});
