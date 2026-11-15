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
