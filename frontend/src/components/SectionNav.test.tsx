import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SectionNav } from "./SectionNav";

function Page() {
  return (
    <>
      <SectionNav refreshKey="KO:1" />
      <div data-section-anchor="Overview" data-section-label="Overview" />
      <div data-section-anchor="Quality" data-section-label="Quality" />
      <div data-section-anchor="Risk Factors" data-section-label="Risk" />
    </>
  );
}

describe("SectionNav", () => {
  it("lists the labelled sections on the page, in page order", async () => {
    render(<Page />);
    const nav = await screen.findByRole("navigation", { name: "Dashboard sections" });
    expect(Array.from(nav.querySelectorAll("button")).map((b) => b.textContent)).toEqual([
      "Overview",
      "Quality",
      "Risk",
    ]);
  });

  it("scrolls to a section when its link is clicked", async () => {
    render(<Page />);
    const target = document.querySelector<HTMLElement>("[data-section-anchor='Risk Factors']")!;
    target.scrollIntoView = vi.fn();
    fireEvent.click(await screen.findByRole("button", { name: "Risk" }));
    expect(target.scrollIntoView).toHaveBeenCalled();
  });

  it("stays hidden with fewer than two sections", () => {
    render(
      <>
        <SectionNav refreshKey="x" />
        <div data-section-anchor="Overview" data-section-label="Overview" />
      </>,
    );
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
