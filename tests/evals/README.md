# Eval harness

A research-report agent that produces beautifully-formatted hallucinations is worse than no agent. The eval harness is the gate that catches that.

## What's here

- **`rubric.py`** — three pure scorers run against any `ResearchReport`:
  1. **Structure** — does the output validate as a `ResearchReport`? (Pydantic invariants enforced.)
  2. **Factuality** — does every numeric fact in `summary` prose also appear in the typed `claims` list? Flags numbers the LLM made up.
  3. **Latency** — wall-clock duration of the agent call.
- **`golden.py`** — a list of golden questions: `(symbol, expected_facts)`. Each `expected_fact` is a value the report is expected to surface (P/E, latest 10-K date, etc.). Empty for now — populated as tools come online.
- **`test_rubric.py`** — unit tests of the rubric framework itself, run on every PR. Validates that the rubric grades known-good and known-bad reports correctly.
- **`test_golden.py`** — runs the agent against each golden question and grades it. **Skipped unless `ANTHROPIC_API_KEY` is set** so it doesn't burn cost on every push. Run manually with `pytest tests/evals/test_golden.py` or add a CI job that runs nightly.

## When evals run

| Trigger | Suite | Why |
|---|---|---|
| Every PR (CI) | `test_rubric.py` | Free, fast — proves the rubric framework is intact |
| Manual / nightly | `test_golden.py` | Real LLM calls — costs money, surfaces factuality regressions |
| Pre-merge for tool PRs | `test_golden.py` | Required before adding a new tool to the agent's registry |

## Adding a golden question

1. Pick a symbol whose report we expect to be stable (large-cap, established, recently filed).
2. Identify 1–3 facts whose ground truth is unambiguous and verifiable from the source data (e.g. "P/E from yfinance.info on date X = Y").
3. Append to `GOLDEN_CASES` in [`golden.py`](golden.py) with the symbol, expected facts, and a tolerance.
4. Run `pytest tests/evals/test_golden.py -k <symbol>` once with a real key — confirm the case passes — before committing.

The rubric is permissive on prose tone but strict on numbers. If a case starts flapping, the most common cause is upstream data shifting (yfinance returning a refreshed P/E); widen the tolerance, don't loosen the rubric.

## Why a separate harness

We intentionally keep evals *out* of the main `pytest` collection (they live under `tests/evals/`, not `tests/`). The reasons:
- Real-LLM eval runs are slow (~30s per case) and cost money.
- Eval failures are signal about the *agent*, not the *code* — flagging them as regular test failures would conflate "did I break a unit?" with "did the model regress?"
- We want PR authors to be able to gate on `test_rubric.py` (free) without paying for `test_golden.py` on every push.
