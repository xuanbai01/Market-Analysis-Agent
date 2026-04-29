/**
 * Symbol input + focus dropdown + refresh toggle.
 *
 * Submission is a controlled form — the parent component drives the
 * actual fetch through TanStack Query so the form stays simple.
 * Symbol is uppercased on submit so "aapl" and "AAPL" hit the same
 * cache key downstream.
 */
import { useState, type FormEvent } from "react";
import type { Focus } from "../lib/schemas";

export interface ReportFormSubmit {
  symbol: string;
  focus: Focus;
  refresh: boolean;
}

interface Props {
  onSubmit: (submit: ReportFormSubmit) => void;
  isPending?: boolean;
  initialSymbol?: string;
}

export function ReportForm({
  onSubmit,
  isPending = false,
  initialSymbol = "",
}: Props) {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [focus, setFocus] = useState<Focus>("full");
  const [refresh, setRefresh] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = symbol.trim().toUpperCase();
    if (!trimmed) return;
    onSubmit({ symbol: trimmed, focus, refresh });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-wrap items-end gap-3 rounded-md border border-slate-200 bg-white p-4 shadow-sm"
    >
      <label className="flex-1 min-w-[180px]">
        <span className="block text-xs font-medium uppercase tracking-wide text-slate-500">
          Symbol
        </span>
        <input
          type="text"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="AAPL"
          maxLength={16}
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          disabled={isPending}
          className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm uppercase shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:bg-slate-100"
        />
      </label>

      <label>
        <span className="block text-xs font-medium uppercase tracking-wide text-slate-500">
          Focus
        </span>
        <select
          value={focus}
          onChange={(e) => setFocus(e.target.value as Focus)}
          disabled={isPending}
          className="mt-1 block rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:bg-slate-100"
        >
          <option value="full">Full (7 sections)</option>
          <option value="earnings">Earnings (3 sections)</option>
        </select>
      </label>

      <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={refresh}
          onChange={(e) => setRefresh(e.target.checked)}
          disabled={isPending}
          className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
        />
        Force refresh
      </label>

      <button
        type="submit"
        disabled={isPending || !symbol.trim()}
        className="self-end rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
      >
        {isPending ? "Working…" : "Generate"}
      </button>
    </form>
  );
}
