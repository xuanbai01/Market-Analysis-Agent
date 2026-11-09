import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ErrorBoundary } from "./ErrorBoundary";

function Boom({ when = true }: { when?: boolean }) {
  if (when) throw new Error("bad data shape");
  return <p>recovered</p>;
}

// React logs caught render errors; keep the test output readable.
let consoleError: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  consoleError.mockRestore();
});

describe("ErrorBoundary", () => {
  it("shows a notice in the broken card's place and leaves its neighbours alone", () => {
    render(
      <>
        <ErrorBoundary label="Quality">
          <Boom />
        </ErrorBoundary>
        <p>Earnings card</p>
      </>,
    );
    const notice = screen.getByRole("alert");
    expect(notice).toHaveTextContent("Quality");
    expect(notice).toHaveTextContent("couldn't be displayed");
    expect(screen.getByText("Earnings card")).toBeInTheDocument();
  });

  it("logs which piece failed", () => {
    render(
      <ErrorBoundary label="Quality">
        <Boom />
      </ErrorBoundary>,
    );
    expect(consoleError).toHaveBeenCalledWith(
      "[Quality] failed to render",
      expect.any(Error),
      expect.anything(),
    );
  });

  it("tries again when the reset key changes", () => {
    const { rerender } = render(
      <ErrorBoundary label="Quality" resetKey="AAPL:1">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(
      <ErrorBoundary label="Quality" resetKey="AAPL:2">
        <Boom when={false} />
      </ErrorBoundary>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("recovered")).toBeInTheDocument();
  });

  it("renders nothing in silent mode", () => {
    const { container } = render(
      <ErrorBoundary label="Market strip" variant="silent">
        <Boom />
      </ErrorBoundary>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("explains a broken page in page mode", () => {
    render(
      <ErrorBoundary label="This page" variant="page">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("page-error")).toHaveTextContent("This page couldn't be displayed.");
  });
});
