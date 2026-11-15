import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InfoTip } from "./chart-kit";

const tip = () => screen.queryByRole("tooltip");
const button = () => screen.getByRole("button", { name: "About IV30" });

describe("InfoTip", () => {
  it("stays open through a click after the focus a browser gives on mousedown", () => {
    render(<InfoTip label="IV30" text="Implied volatility 30 days out." />);
    fireEvent.focus(button());
    fireEvent.click(button());
    expect(tip()).toHaveTextContent("Implied volatility 30 days out.");
  });

  it("stays open through a click after the pointer has entered", () => {
    render(<InfoTip label="IV30" text="Implied volatility 30 days out." />);
    fireEvent.mouseEnter(button().parentElement as HTMLElement);
    fireEvent.click(button());
    expect(tip()).not.toBeNull();
  });

  it("opens leftward when it would run past the screen's right edge", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 375 });
    render(<InfoTip label="IV30" text="Implied volatility 30 days out." />);
    const anchor = button().parentElement as HTMLElement;
    anchor.getBoundingClientRect = () => ({ left: 300, right: 310, top: 0, bottom: 10, width: 10, height: 10, x: 300, y: 0, toJSON: () => ({}) });
    fireEvent.click(button());
    expect(tip()?.className).toContain("right-0");
    fireEvent.blur(button());
    anchor.getBoundingClientRect = () => ({ left: 20, right: 30, top: 0, bottom: 10, width: 10, height: 10, x: 20, y: 0, toJSON: () => ({}) });
    fireEvent.click(button());
    expect(tip()?.className).toContain("left-0");
  });

  it("opens on a tap alone, and closes on blur, on leaving and on Escape", () => {
    render(<InfoTip label="IV30" text="Implied volatility 30 days out." />);
    fireEvent.click(button());
    expect(tip()).not.toBeNull();
    fireEvent.blur(button());
    expect(tip()).toBeNull();
    fireEvent.mouseEnter(button().parentElement as HTMLElement);
    fireEvent.mouseLeave(button().parentElement as HTMLElement);
    expect(tip()).toBeNull();
    fireEvent.focus(button());
    fireEvent.keyDown(button(), { key: "Escape" });
    expect(tip()).toBeNull();
  });
});
