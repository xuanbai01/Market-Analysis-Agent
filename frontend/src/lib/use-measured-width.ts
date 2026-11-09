/**
 * The rendered size of an element, for SVG charts that draw in real
 * pixels (so 11 px labels stay 11 px). ``null`` until measured — and
 * always in happy-dom, which has no layout — so callers keep a fallback.
 */
import { useCallback, useRef, useState } from "react";

export interface MeasuredSize {
  width: number;
  height: number;
}

export function useMeasuredSize(): [(el: HTMLElement | null) => void, MeasuredSize | null] {
  const [size, setSize] = useState<MeasuredSize | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      const width = Math.round(rect?.width ?? 0);
      const height = Math.round(rect?.height ?? 0);
      if (width > 0) {
        setSize((prev) => (prev && prev.width === width && prev.height === height ? prev : { width, height }));
      }
    });
    ro.observe(el);
    observer.current = ro;
  }, []);
  return [ref, size];
}

export function useMeasuredWidth(): [(el: HTMLElement | null) => void, number | null] {
  const [ref, size] = useMeasuredSize();
  return [ref, size?.width ?? null];
}
