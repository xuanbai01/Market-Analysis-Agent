import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { clearStoredToken } from "../../lib/auth";
import { clearOwnerKey, getOwnerKey, setOwnerKey, useOwnerKey } from "../../lib/owner";
import * as ownerApi from "../../lib/owner-api";
import { OWNER_USERNAME, OwnerUnlock } from "./OwnerUnlock";

afterEach(() => {
  clearOwnerKey();
  vi.restoreAllMocks();
});

describe("the owner key in this browser", () => {
  it("goes when the sign-in goes, whatever ended it (a 401 included)", () => {
    setOwnerKey("k".repeat(40));
    clearStoredToken();
    expect(getOwnerKey()).toBeNull();
  });

  it("lasts the page in memory when storage refuses it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("private mode");
    });
    setOwnerKey("k".repeat(40));
    expect(getOwnerKey()).toBe("k".repeat(40));
  });

  it("asks the server without following a redirect, and never caches", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ tastytrade: true }), { status: 200 }));
    await ownerApi.fetchOwnerStatus("k".repeat(40));
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.redirect).toBe("error");
    expect(init.cache).toBe("no-store");
    expect((init.headers as Record<string, string>)[ownerApi.OWNER_HEADER]).toBe("k".repeat(40));
  });

  it("is kept, read back and forgotten, and a hook follows it", () => {
    const { result } = renderHook(() => useOwnerKey());
    expect(result.current).toBeNull();
    act(() => setOwnerKey("k".repeat(40)));
    expect(getOwnerKey()).toBe("k".repeat(40));
    expect(result.current).toBe("k".repeat(40));
    act(() => clearOwnerKey());
    expect(result.current).toBeNull();
  });
});

function submit(key: string) {
  fireEvent.change(screen.getByLabelText("Owner key"), { target: { value: key } });
  fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
}

describe("OwnerUnlock", () => {
  it("is a form a password manager saves and syncs, under its own name", () => {
    const { container } = render(<OwnerUnlock />);
    const username = container.querySelector('input[autocomplete="username"]');
    expect(username).toHaveValue(OWNER_USERNAME);
    expect(username).not.toBeVisible();
    expect(container.querySelector('input[type="password"]')).toHaveAttribute("autocomplete", "current-password");
    expect(container.querySelector("form")).toHaveAttribute("method", "post");
  });

  it("keeps the key only once the server accepts it", async () => {
    const check = vi.spyOn(ownerApi, "fetchOwnerStatus").mockResolvedValue({ tastytrade: true });
    const unlocked = vi.fn();
    render(<OwnerUnlock onUnlocked={unlocked} />);
    submit("right-key");
    await waitFor(() => expect(unlocked).toHaveBeenCalled());
    expect(check).toHaveBeenCalledWith("right-key");
    expect(getOwnerKey()).toBe("right-key");
  });

  it.each([
    [new ApiError({ status: 403, title: "x" }), "That isn't the owner key."],
    [new ApiError({ status: 404, title: "x" }), /no owner key yet/],
    [new ApiError({ status: 429, title: "x", retryAfterSeconds: 300 }), /try again in about 5 minutes/],
    [new ApiError({ status: 401, title: "x" }), /sign in again/],
  ])("says why a key was refused, and keeps nothing", async (error, message) => {
    vi.spyOn(ownerApi, "fetchOwnerStatus").mockRejectedValue(error);
    render(<OwnerUnlock />);
    submit("wrong-key");
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(getOwnerKey()).toBeNull();
  });
});
