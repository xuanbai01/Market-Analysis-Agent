"""
Render a claim value the way the dashboard shows it.

Python mirror of ``frontend/src/lib/format.ts::formatClaimValue`` for
unit-annotated claims (``Claim.unit``, Phase 4.3.X). The synth prompt
uses it so the LLM sees "Return on equity = 142.26%" — what the reader
sees on the card — instead of the stored ``1.4226``. Without it the
model copied raw values into prose and compared numbers stored in
different forms (a 1.74% buyback yield is stored ``0.0174``, a 0.32%
dividend yield ``0.32``), inverting the real comparison
(tasks/dogfood-2026-11.md #1).

Claims without a unit (tools not yet annotated) keep ``repr(value)``,
exactly what the prompt sent before. Display strings stay compatible
with the eval rubric: it accepts fraction→percent and $T/$B/$M forms.
"""
from __future__ import annotations

from typing import Any

from app.schemas.research import ClaimUnit

_SCALES = ((1e12, "T"), (1e9, "B"), (1e6, "M"))


def _scaled(abs_n: float) -> str | None:
    for size, suffix in _SCALES:
        if abs_n >= size:
            return f"{abs_n / size:.2f}{suffix}"
    return None


def _grouped(n: float) -> str:
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.2f}"


def format_claim_value(value: object, unit: ClaimUnit | None) -> str:
    """Display form of ``value`` for ``unit``; ``repr`` when unannotated."""
    if value is None:
        return "None"
    if unit is None:
        return repr(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if unit in ("string", "date") or not isinstance(value, int | float):
        return str(value)

    n = float(value)
    sign = "-" if n < 0 else ""
    abs_n = abs(n)
    if unit == "fraction":
        return f"{n * 100:.2f}%"
    if unit == "percent":
        return f"{n:.2f}%"
    if unit == "usd_per_share":
        return f"{sign}${abs_n:.2f}"
    if unit == "usd":
        return f"{sign}${_scaled(abs_n) or f'{abs_n:.2f}'}"
    if unit == "ratio":
        return f"{n:.2f}"
    if unit == "shares":
        scaled = _scaled(abs_n)
        return f"{sign}{scaled}" if scaled else _grouped(n)
    if unit == "count":
        return _grouped(n) if float(n).is_integer() else f"{n:.2f}"
    if unit == "basis_points":
        return f"{n * 10_000:.0f} bps"
    if unit == "percentage_points":
        pts = round(n * 100, 2)
        if pts == 0:
            return "0.00 pts"  # not "-0.00" for a tiny negative
        return f"{'+' if pts > 0 else ''}{pts:.2f} pts"
    return repr(value)


def format_claim_line(c: Any, claim_id: str | None = None) -> str:
    """One prompt line per claim: ``- description = value (tool)``.

    Unit-annotated values go in display form ("142.26%", "$4.98T"), the
    same text the dashboard card shows, so prose matches the cards and
    never compares numbers stored in different forms. Unannotated claims
    keep ``repr``.

    ADR 0007: a claim with history adds its path — first → last, low and
    high, in the same display units — so the model can describe a trend
    using numbers that are history points (and pass the rubric).
    ``claim_id`` prefixes the line ("- [Q3] ...") for prompts that ask
    the model to cite claims by id (the analyst view).
    """
    unit = getattr(c, "unit", None)
    tag = f"[{claim_id}] " if claim_id else ""
    line = f"- {tag}{c.description} = {format_claim_value(c.value, unit)} ({c.source.tool})"
    history = list(getattr(c, "history", None) or [])
    if len(history) < 2:
        return line

    def fmt(point: Any) -> str:
        return format_claim_value(point.value, unit)

    first, last = history[0], history[-1]
    low = min(history, key=lambda p: p.value)
    high = max(history, key=lambda p: p.value)
    return (
        f"{line} · history {len(history)} periods: {first.period} {fmt(first)} → "
        f"{last.period} {fmt(last)}; low {fmt(low)} ({low.period}), "
        f"high {fmt(high)} ({high.period})"
    )
