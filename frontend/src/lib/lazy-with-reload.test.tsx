/**
 * lazy-with-reload tests (2026-11). After a deploy, a tab opened before
 * it asks for chunk names the new build doesn't have; the page reloads
 * once to pick up the new entry, and never loops.
 */
import { Suspense } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "../components/ErrorBoundary";
import { RELOAD_WINDOW_MS, lazyWithReload, reloadForNewDeploy } from "./lazy-with-reload";

const T0 = 1_800_000_000_000;

beforeEach(() => window.sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("reloadForNewDeploy", () => {
  it("reloads once, then not again within the window", () => {
    const reload = vi.fn();
    expect(reloadForNewDeploy(reload, T0)).toBe(true);
    expect(reloadForNewDeploy(reload, T0 + RELOAD_WINDOW_MS - 1)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reloads again once the window has passed", () => {
    const reload = vi.fn();
    reloadForNewDeploy(reload, T0);
    expect(reloadForNewDeploy(reload, T0 + RELOAD_WINDOW_MS)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("does not reload when storage is blocked (no loop guard)", () => {
    // Blocked site data: reading window.sessionStorage itself throws.
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const reload = vi.fn();
    expect(reloadForNewDeploy(reload, T0)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});

describe("lazyWithReload", () => {
  const chunkError = () =>
    Promise.reject(new TypeError("Failed to fetch dynamically imported module: /assets/Page-old.js"));

  function renderLazy(load: () => Promise<{ default: () => JSX.Element }>, reload: () => void) {
    const Page = lazyWithReload(load, reload);
    return render(
      <ErrorBoundary label="This page" variant="page">
        <Suspense fallback={<p>loading</p>}>
          <Page />
        </Suspense>
      </ErrorBoundary>,
    );
  }

  it("renders the component when the chunk loads", async () => {
    const reload = vi.fn();
    renderLazy(() => Promise.resolve({ default: () => <p>dashboard</p> }), reload);
    expect(await screen.findByText("dashboard")).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads on a failed chunk and stays on the fallback meanwhile", async () => {
    const reload = vi.fn();
    renderLazy(chunkError, reload);
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(screen.getByText("loading")).toBeTruthy();
    expect(screen.queryByText(/couldn't be displayed/i)).toBeNull();
  });

  it("shows the error boundary when the chunk fails again right after a reload", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    window.sessionStorage.setItem("market-agent.chunk-reload-at", String(Date.now()));
    const reload = vi.fn();
    renderLazy(chunkError, reload);
    expect(await screen.findByText(/couldn't be displayed/i)).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
  });
});
