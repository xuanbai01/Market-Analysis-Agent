# ADR 0006: Make the LLM provider switchable, and add DeepSeek

**Status:** Accepted
**Date:** 2026-11-07
**Deciders:** Project owner

## Context

Every fresh research report makes one synthesis call (the section
summaries + card narratives) and up to two classification calls (risk
paragraph and news headline categorizers). Since Phase 2 these ran on
Claude Sonnet 4.6 (synth) and Haiku 4.5 (triage), hard-coded in
`app/services/llm.py`.

DeepSeek V4.1 Flash (`deepseek-flash`) lists at $0.15 / $0.60 per 1M
input / output tokens off-peak ($0.30 / $1.20 peak), against Sonnet
4.6's $3 / $15 — roughly 20–25× cheaper per token. The project owner
bought DeepSeek credit and wants it as the default, while keeping
Sonnet and Haiku one setting away.

The constraint that matters is not cost (a few dollars a month at
personal-use volume) but **citation discipline**: summary prose may
only cite numbers present in that section's claims. The golden eval
(`tests/evals/`) enforces factuality ≥ 0.95, and any provider has to
clear the same bar.

## Options considered

### Option 1: Replace Anthropic with DeepSeek outright
- Pros: one code path.
- Cons: no way back without a code change; can't A/B the two on the eval.

### Option 2: Use DeepSeek's Anthropic-compatible endpoint with the existing SDK
- Pros: smallest diff — swap `base_url`, key, and model.
- Cons: a compatibility layer over a third-party API; DeepSeek documents
  forced tool choice, thinking mode and caching for its OpenAI-format API,
  not for this endpoint. Prompt-caching and `tool_choice` semantics would
  be guesses.

### Option 3: Provider switch behind the existing `triage_call` / `synth_call`
- Pros: callers unchanged; switching is an env change; both providers stay
  tested; the eval can grade either.
- Cons: a second adapter and SDK (`openai`) to maintain.

## Decision

Option 3. `settings.LLM_PROVIDER` (`anthropic` | `deepseek`, a Literal so
typos fail at boot) selects the adapter at call time;
`LLM_TRIAGE_MODEL` / `LLM_SYNTH_MODEL` override each tier's model
(defaults: Haiku 4.5 / Sonnet 4.6 on Anthropic, `deepseek-flash` for both
tiers on DeepSeek). The DeepSeek adapter (`app/services/llm_deepseek.py`)
uses the `openai` SDK against `https://api.deepseek.com`, forces the named
function with **thinking disabled** (DeepSeek rejects a named
`tool_choice` in thinking mode, which is its default), inlines Pydantic
`$defs`/`$ref`, and reads cache hits from `prompt_cache_hit_tokens`.
Strict function calling is not used — it needs every field required —
so Pydantic validation stays the safety net, as on the Anthropic path.

Both adapters convert provider API errors into `RuntimeError`, which the
research router already maps to 503.

The code default stays `anthropic`, so deploying this changes nothing in
production until `LLM_PROVIDER=deepseek` and `DEEPSEEK_API_KEY` are set
as Fly secrets. Local `.env` uses DeepSeek.

## Evidence (live golden eval, 2026-11-07, `deepseek-flash`, off-peak)

| Ticker | Factuality, first run | Factuality, fixed rubric (fresh run) | Synth tokens in / out | Cost (off-peak) |
|---|---|---|---|---|
| AAPL | 0.952 | 0.988 | 3,605 / 1,388 | $0.0042 |
| NVDA | 1.000 | 1.000 | 3,509 / 1,217 | $0.0042 |
| RIVN | 1.000 | 1.000 | 3,320 / 1,312 | $0.0086 |
| JPM | 0.762 (0.918 on rerun) | 0.967 | 3,226 / 1,128 | $0.0010 |
| KO | 0.976 | 0.987 | 3,433 / 1,309 | $0.0023 |

The second column is a fresh generation, so its prose differs from the
first run's; all five clear the 0.95 gate.

All five reports were structurally valid. Every number the rubric
flagged was checked by hand against the claims and was grounded. The
misses came from two rubric bugs, both fixed alongside this ADR:

- **Unit suffixes were truncated.** The number regex ended in `\b`, so
  "14.03x" was read as 14 and "$888.27B" as 888 (JPM's 14, 13, 11, 888).
  The same bug could pass a fabricated "14.9x" on its integer part.
- **Numbers in claim text didn't count.** "20" from "last 20 quarters"
  (a claim *description*), "10" from "10-K", and founding years from the
  business summary (JPM 1799, KO 1886) were flagged because only claim
  *values* were matched. They now count when quoted literally in the
  same section's claims.

JPM suffered most because a bank has few numeric claims, so each false
positive weighed more. No fabricated figure was found.

Peak-hour cost is double. The same token counts on Sonnet 4.6 come to
roughly $0.03 per report for synthesis alone, so DeepSeek is about
10× cheaper per report in practice.

The run also exposed a provider-independent bug: RIVN's 248-paragraph
10-K diff overflowed the risk categorizer's fixed 4096-token output
ceiling (`finish_reason=length`), so the card silently fell back to
aggregate bars. The categorizer's budget now scales with the paragraph
count.

## Consequences

### Easier

- Moving between DeepSeek, Sonnet and Haiku is a restart with a new env value.
- Running the golden eval on any provider/model combination.
- Adding a third OpenAI-format provider is mostly a base URL and a key.

### Harder

- Two SDKs and two adapters to keep current; provider-specific quirks
  (DeepSeek thinking mode, Anthropic `cache_control`) live in separate code.
- Prose quality can differ between providers even when factuality passes —
  the eval checks numbers, not tone.

### Locked-in

- The forced-single-tool + Pydantic-validation contract. Any future
  provider must support forcing a named function (or be adapted to
  structured output).

## Revisit when

- DeepSeek's factuality on the golden set drops below 0.95, or users
  notice weaker prose on the dashboard.
- A Sonnet run on the same golden set shows a clear quality gap.
- DeepSeek changes the thinking-mode / `tool_choice` rules, or removes
  the `deepseek-flash` alias.
- Data-residency requirements appear (DeepSeek's first-party API is
  hosted in China; US hosts serve the open weights).
