/**
 * lazy-with-reload — route chunks that survive a deploy (2026-11).
 *
 * Vite names each chunk by its content hash. A tab opened before a
 * deploy still runs the old entry, which asks for the old chunk names
 * (``SymbolDetailPage-K0cGJI8t.js``); the new deploy doesn't have them,
 * the import fails, and the page showed "This page couldn't be
 * displayed" until the reader reloaded by hand.
 *
 * ``lazyWithReload`` reloads the page once when a lazy import fails, so
 * the tab picks up the new entry and its chunk names. A timestamp in
 * sessionStorage stops a loop: a second failure within
 * ``RELOAD_WINDOW_MS`` (a chunk that is really broken, or the network is
 * down) goes to the error boundary as before. Without storage there is
 * no guard, so it doesn't reload at all.
 *
 * vercel.json's SPA rewrite skips ``/assets/``: a missing chunk is a
 * 404 rather than ``index.html`` served as a script (the browser's
 * "MIME type text/html" error).
 */
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

const RELOAD_KEY = "market-agent.chunk-reload-at";
export const RELOAD_WINDOW_MS = 10_000;

type Reload = () => void;

const reloadPage: Reload = () => window.location.reload();

/** Reload unless one already happened within the window. True when it reloads. */
export function reloadForNewDeploy(reload: Reload = reloadPage, now: number = Date.now()): boolean {
  try {
    const last = Number(window.sessionStorage.getItem(RELOAD_KEY)) || 0;
    if (now - last < RELOAD_WINDOW_MS) return false;
    window.sessionStorage.setItem(RELOAD_KEY, String(now));
  } catch {
    return false; // storage blocked: no loop guard, so no reload
  }
  reload();
  return true;
}

/** ``React.lazy`` that reloads once when the chunk fails to load. */
export function lazyWithReload<P extends object>(
  load: () => Promise<{ default: ComponentType<P> }>,
  reload: Reload = reloadPage,
): LazyExoticComponent<ComponentType<P>> {
  return lazy(() =>
    load().catch((error: unknown) => {
      // While the page reloads, stay suspended (the route's fallback
      // shows) rather than flash the error boundary.
      if (reloadForNewDeploy(reload)) return new Promise<never>(() => {});
      throw error;
    }),
  );
}
