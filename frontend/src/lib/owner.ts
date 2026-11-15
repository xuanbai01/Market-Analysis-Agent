/**
 * The owner key (ADR 0009, amended 2026-11-15): a second key, on top of
 * the shared secret, for the owner's account routes (``/v1/owner``). Kept
 * in this browser like the shared secret and cleared on sign out; the
 * unlock form is built so a password manager saves it and syncs it to the
 * owner's other PCs. Small on purpose: the sidebar imports it.
 */
import { useSyncExternalStore } from "react";

const OWNER_KEY_STORAGE = "market-agent.owner-key";
const CHANGED = "market-agent:owner-key";

export function getOwnerKey(): string | null {
  try {
    return window.localStorage.getItem(OWNER_KEY_STORAGE);
  } catch {
    return null; // private mode: no key, the unlock form asks again
  }
}

function changed(): void {
  window.dispatchEvent(new Event(CHANGED));
}

export function setOwnerKey(key: string): void {
  try {
    window.localStorage.setItem(OWNER_KEY_STORAGE, key);
  } catch {
    // storage refused: the key lasts until the page reloads
  }
  changed();
}

/** Forget the owner key: on sign out, and when the server refuses it. */
export function clearOwnerKey(): void {
  try {
    window.localStorage.removeItem(OWNER_KEY_STORAGE);
  } catch {
    // see above
  }
  changed();
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange); // another tab
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The stored owner key, kept current as it's set or cleared (any tab). */
export function useOwnerKey(): string | null {
  return useSyncExternalStore(subscribe, getOwnerKey, () => null);
}
