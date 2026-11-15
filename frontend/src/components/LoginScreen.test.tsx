import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { LoginScreen } from "./LoginScreen";

describe("LoginScreen", () => {
  it("is a sign-in form a password manager can save and sync to another PC", () => {
    vi.spyOn(api, "fetchDemoIndex").mockResolvedValue({ symbols: [] });
    const { container } = render(
      <MemoryRouter>
        <LoginScreen onAuthenticated={() => undefined} />
      </MemoryRouter>,
    );
    // A password-only form has no username, so a manager can't tell one
    // saved secret from another; a fixed, hidden one names it.
    const username = container.querySelector('input[autocomplete="username"]');
    expect(username).not.toBeNull();
    expect(username).toHaveValue("market-agent");
    expect(username).not.toBeVisible();
    const password = container.querySelector('input[type="password"]');
    expect(password).toHaveAttribute("autocomplete", "current-password");
    expect(password).toHaveAttribute("name", "password");
  });
});
