"""
LLM client with cost-tier routing.

Two callables — ``triage_call`` and ``synth_call`` — produce a typed
Pydantic instance from a prompt by forcing the model to populate a
single tool whose ``input_schema`` is the Pydantic JSON schema. The
forced-tool pattern is more robust than JSON mode against malformed
output: the SDK either gives us a parseable tool_use block or raises.

Cost-tier routing is deliberate: agentic planning ("which of these N
tools should I call?") is a triage decision well within Haiku's
capabilities, while the final synthesis ("turn these claims into a
research report") is where Sonnet earns its 3× input / 3× output
premium. The split typically saves 60–80% of token cost vs always
running on Sonnet — to be re-measured after the agent ships and
documented in a follow-up ADR.

System prompts are cached via ``cache_control: ephemeral``. Identical
system prompts across calls (same role / instructions / tool list) hit
the cache and pay ~0.1× per repeat. Verify hits via
``response.usage.cache_read_input_tokens``.

Every call is wrapped in ``log_external_call`` so service id, input
shape, output shape (token counts), latency, and outcome land in the
A09 log stream.
"""
from __future__ import annotations

from typing import TypeVar

from anthropic import AsyncAnthropic, NotGiven
from pydantic import BaseModel

from app.core.observability import log_external_call
from app.core.settings import settings

# ── Models ────────────────────────────────────────────────────────────
# Keep these in one place so a model bump is a one-line change.
TRIAGE_MODEL = "claude-haiku-4-5"          # tool selection / planning
SYNTH_MODEL = "claude-sonnet-4-6"          # report synthesis

# Default per-call token ceiling. Forced-schema tool calls rarely need
# more than a few KB; bump per call if synthesizing a 10-section report.
DEFAULT_MAX_TOKENS = 4096

# Name of the single tool the model is forced to call. Arbitrary string
# — we never expose it to the user — but stable for cache-prefix safety.
_SUBMIT_TOOL_NAME = "submit_response"


T = TypeVar("T", bound=BaseModel)


# Lazy-initialized so the module can be imported without an API key
# present (tests, the eval-rubric unit tests, etc.). The first real call
# triggers construction; an empty key raises a clear error instead of a
# generic 401 from the API.
_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Run `cp .env.example .env` and fill it in for local dev, "
                "or `fly secrets set ANTHROPIC_API_KEY=...` for production.",
            )
        _client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _build_tool(schema: type[BaseModel]) -> dict:
    """Wrap a Pydantic schema as a single forced tool definition."""
    return {
        "name": _SUBMIT_TOOL_NAME,
        "description": (
            "Submit your response. The input must conform exactly to the "
            "schema; do not include free-form text or commentary."
        ),
        "input_schema": schema.model_json_schema(),
    }


def _build_system(system: str | None) -> list[dict] | NotGiven:
    """
    System prompt with prompt caching enabled on the last (only) block.

    We pass system as a list-of-blocks even when there's just one block,
    because that's the form that accepts ``cache_control``. Identical
    system text across calls hits the prefix cache. See
    ``shared/prompt-caching.md`` for the audit checklist if hits stop
    accumulating (most common cause: timestamps in the system prompt).
    """
    if not system:
        return NotGiven()
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},  # 5-min default TTL
        }
    ]


async def _structured_call(
    *,
    model: str,
    schema: type[T],
    prompt: str,
    system: str | None,
    max_tokens: int,
    service_id: str,
) -> T:
    """Shared implementation for triage_call and synth_call."""
    client = _get_client()
    tool_def = _build_tool(schema)

    with log_external_call(
        service_id,
        {
            "model": model,
            "schema": schema.__name__,
            "prompt_chars": len(prompt),
            "system_chars": len(system) if system else 0,
            "max_tokens": max_tokens,
        },
    ) as call:
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_build_system(system),
            messages=[{"role": "user", "content": prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": _SUBMIT_TOOL_NAME},
        )

        # Find the tool_use block — with forced tool_choice, the model
        # MUST emit one. If it didn't, that's a contract violation worth
        # surfacing loudly rather than papering over.
        tool_use = next((b for b in msg.content if b.type == "tool_use"), None)
        if tool_use is None:
            raise RuntimeError(
                f"Model {model} returned no tool_use block under forced "
                f"tool_choice. stop_reason={msg.stop_reason!r}"
            )

        # Token accounting + cache effectiveness — both go in the
        # observability record so we can chart cost over time and catch
        # cache regressions in production.
        call.record_output(
            {
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
                "cache_creation_input_tokens": getattr(
                    msg.usage, "cache_creation_input_tokens", 0
                ),
                "cache_read_input_tokens": getattr(
                    msg.usage, "cache_read_input_tokens", 0
                ),
                "stop_reason": msg.stop_reason,
            }
        )

        # Pydantic validates the LLM's output against the schema — any
        # mismatch raises ValidationError, surfaced to the caller.
        return schema.model_validate(tool_use.input)


async def triage_call(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> T:
    """
    Small-model call for tool-selection / planning. Use for any
    structured decision where Haiku-class capability is sufficient
    (which-tool-to-call, classify intent, extract a known-shape entity).
    """
    return await _structured_call(
        model=TRIAGE_MODEL,
        schema=schema,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        service_id="anthropic.triage",
    )


async def synth_call(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> T:
    """
    Capable-model call for synthesis. Use for the final write-up where
    quality matters (the research report itself, multi-source
    reconciliation, nuanced summary).
    """
    return await _structured_call(
        model=SYNTH_MODEL,
        schema=schema,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        service_id="anthropic.synth",
    )
