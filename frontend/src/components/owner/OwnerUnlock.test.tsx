import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../lib/api";
import { clearOwnerKey, getOwnerKey, setOwnerKey, useOwnerKey } from "../../lib/owner";
import * as ownerApi from "../../lib/owner-api";
import { OWNER_USERNAME, OwnerUnlock } from "./OwnerUnlock";

afterEach(() => {
  clearOwnerKey();
  vi.restoreAllMocks();
});

describe("the owner key in this browser", () => {
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
