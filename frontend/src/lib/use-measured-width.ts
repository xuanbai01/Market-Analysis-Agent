/**
 * The rendered width of an element, for SVG charts that draw in real
 * pixels (so 11 px labels stay 11 px). ``null`` until measured — and
 * always in happy-dom, which has no layout — so callers keep a fallback.
 */
import { useCallback, useRef, useState } from "react";

export function useMeasuredWidth(): [(el: HTMLElement | null) => void, number | null] {
  const [width, setWidth] = useState<number | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setWidth((prev) => (prev === w ? prev : w));
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  return [ref, width];
}
