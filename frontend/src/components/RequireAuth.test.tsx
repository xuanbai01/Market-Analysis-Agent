/**
 * RequireAuth tests (Phase 4.0).
 *
 * RequireAuth is the route-guard wrapper for authenticated routes.
 *
 * Behavior:
 * 1. No token → redirect to /login, preserving the original URL via
 *    location state so post-login can route back.
 * 2. Token present → render children unchanged.
 * 3. localStorage 'storage' event from another tab logs us out → on
 *    next render, redirect to /login.
 */
import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RequireAuth } from "./RequireAuth";
import { setStoredToken, clearStoredToken } from "../lib/auth";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/symbol/:ticker"
          element={
            <RequireAuth>
              <div data-testid="protected">protected content</div>
            </RequireAuth>
          }
        />
        <Route
          path="/login"
          element={<div data-testid="login-page">login</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequireAuth", () => {
  beforeEach(() => {
    clearStoredToken();
  });

  it("redirects to /login when no token is set", () => {
    renderAt("/symbol/AAPL");
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("renders children when a token is set", () => {
    setStoredToken("test-secret");
    renderAt("/symbol/AAPL");
    expect(screen.getByTestId("protected")).toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
  });
});
