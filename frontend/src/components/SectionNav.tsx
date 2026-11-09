/**
 * SectionNav — a sticky row of links to the dashboard's sections.
 *
 * Built from the ``data-section-anchor`` / ``data-section-label``
 * elements actually on the page, in page order — so it never lists a
 * card that didn't render, and the distressed layout's reordering shows
 * up here for free. The section in view is highlighted (scroll-spy via
 * IntersectionObserver; skipped where that API doesn't exist).
 *
 * Anchored elements carry ``scroll-mt-16`` so a jump lands below this bar.
 */
import { useEffect, useState } from "react";

import { scrollToSection } from "../lib/thesis";

interface Props {
  /** Re-scan when this changes (another ticker or a regenerated report). */
  refreshKey: string;
}

interface Item {
  anchor: string;
  label: string;
}

export function SectionNav({ refreshKey }: Props) {
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const elements = Array.from(document.querySelectorAll<HTMLElement>("[data-section-label]"));
    setItems(
      elements.map((el) => ({
        anchor: el.dataset.sectionAnchor ?? "",
        label: el.dataset.sectionLabel ?? "",
      })),
    );
    if (typeof IntersectionObserver === "undefined") return;
    const inView = new Map<string, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          inView.set((entry.target as HTMLElement).dataset.sectionAnchor ?? "", entry.isIntersecting);
        }
        const first = elements.find((el) => inView.get(el.dataset.sectionAnchor ?? ""));
        if (first) setActive(first.dataset.sectionAnchor ?? null);
      },
      // The band just under the sticky bar decides which section is "current".
      { rootMargin: "-72px 0px -55% 0px" },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [refreshKey]);

  if (items.length < 2) return null;

  return (
    <nav
      aria-label="Dashboard sections"
      data-testid="section-nav"
      className="sticky top-0 z-20 -mx-6 mb-4 border-b border-strata-line bg-strata-canvas/90 px-6 backdrop-blur lg:-mx-8 lg:px-8 xl:-mx-10 xl:px-10"
    >
      <ul className="flex gap-1 overflow-x-auto py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {items.map((item) => {
          const current = item.anchor === active;
          return (
            <li key={item.anchor}>
              <button
                type="button"
                aria-current={current ? "location" : undefined}
                onClick={() => scrollToSection(item.anchor)}
                className={[
                  "whitespace-nowrap rounded-md px-2.5 py-1 font-mono text-[11px] transition-colors",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight",
                  current
                    ? "bg-strata-raise text-strata-hi"
                    : "text-strata-dim hover:bg-strata-raise hover:text-strata-fg",
                ].join(" ")}
              >
                {item.label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
