// Loaded by vitest before each test file (configured in vite.config.ts).
// jest-dom matchers are imported globally so tests get
// expect(el).toBeInTheDocument() and friends without per-file imports.
import "@testing-library/jest-dom";
import { beforeEach } from "vitest";

// happy-dom 15 + Node 25 has a known issue where ``window.localStorage``
// is an empty object instead of a real Storage implementation
// (Node's experimental ``--localstorage-file`` feature interferes).
// Polyfill with a Map-backed Storage so our auth tests can exercise
// the same API the production code uses.
function makeStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.get(key) ?? null;
    },
    key(i: number) {
      return Array.from(store.keys())[i] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, String(value));
    },
  };
}

Object.defineProperty(window, "localStorage", {
  value: makeStorage(),
  writable: true,
  configurable: true,
});

beforeEach(() => {
  window.localStorage.clear();
});
