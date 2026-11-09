/**
 * ErrorBoundary — keeps one broken piece from blanking the whole app.
 *
 * Without a boundary, a render error anywhere (one card meeting a data
 * shape it didn't expect) unmounts the entire React tree: white screen,
 * sidebar included. Wrapped pieces fail alone:
 *
 *   variant "card"   — a small notice in the card's place
 *   variant "page"   — a notice in the page area; sidebar + strip stay
 *   variant "silent" — renders nothing (optional chrome, e.g. the strip)
 *
 * ``resetKey``: when it changes (another ticker, a regenerated report,
 * another route) the boundary renders its children again.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  /** What failed, in the user's words: "Quality", "This page". */
  label: string;
  variant?: "card" | "page" | "silent";
  resetKey?: unknown;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`[${this.props.label}] failed to render`, error, info.componentStack);
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render(): ReactNode {
    const { error } = this.state;
    const { label, variant = "card", children } = this.props;
    if (!error) return children;
    if (variant === "silent") return null;

    if (variant === "page") {
      return (
        <div role="alert" data-testid="page-error" className="mx-auto max-w-xl px-6 py-16 text-center">
          <p className="text-sm font-medium text-strata-hi">{label} couldn&apos;t be displayed.</p>
          <p className="mt-2 text-xs text-strata-dim">
            Something in the data broke the page. Open another page from the sidebar, or reload.
          </p>
        </div>
      );
    }
    return (
      <div
        role="alert"
        data-testid="card-error"
        className="rounded-md border border-dashed border-strata-border bg-strata-surface px-5 py-6 text-center"
      >
        <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{label}</p>
        <p className="mt-2 text-xs text-strata-dim">
          This card couldn&apos;t be displayed. The rest of the report is unaffected.
        </p>
      </div>
    );
  }
}
