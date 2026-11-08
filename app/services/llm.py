"""
LLM client with cost-tier routing and a pluggable provider.

Two callables — ``triage_call`` and ``synth_call`` — produce a typed
Pydantic instance from a prompt by forcing the model to populate a
single tool whose input schema is the Pydantic JSON schema. The
forced-tool pattern is more robust than JSON mode against malformed
output: the SDK either gives us a parseable tool call or we raise.

Provider switch (ADR 0006): ``settings.LLM_PROVIDER`` picks the backend
at call time — ``anthropic`` (Claude, the default) or ``deepseek``
(OpenAI-format API; adapter in ``llm_deepseek``). Each tier's model has
a per-provider default and can be overridden with ``LLM_TRIAGE_MODEL``
/ ``LLM_SYNTH_MODEL``, so "back to Sonnet" or "synth on Haiku" is an
env change, not a code change. Callers never see the provider: same
signatures, same Pydantic output, and every provider failure surfaces
as ``RuntimeError`` (→ 503 at the research router).

Cost-tier routing: triage (classification — the risk and news
categorizers) runs on the cheap tier; synthesis (the report prose) on
the capable tier. On Anthropic that's Haiku vs Sonnet; DeepSeek Flash
is cheap enough to serve both.

Anthropic system prompts are cached via ``cache_control: ephemeral``;
DeepSeek caches prefixes automatically. Both report hits as
``cache_read_input_tokens`` in the observability record.

Every call is wrapped in ``log_external_call`` under service id
``<provider>.<tier>`` so model, input shape, token counts, latency, and
outcome land in the A09 log stream.
"""
from __future__ import annotations

from typing import Literal, TypeVar

import anthropic
from anthropic import AsyncAnthropic, NotGiven
from pydantic import BaseModel

from app.core.observability import log_external_call
from app.core.settings import settings
from app.services import llm_deepseek

Tier = Literal["triage", "synth"]

# ── Models ────────────────────────────────────────────────────────────
# Per-provider default for each tier. A model bump is a one-line change
# here; a per-deployment switch is LLM_<TIER>_MODEL in the environment.
DEFAULT_MODELS: dict[str, dict[Tier, str]] = {
    "anthropic": {"triage": "claude-haiku-4-5", "synth": "claude-sonnet-4-6"},
    "deepseek": {"triage": "deepseek-flash", "synth": "deepseek-flash"},
}

# Default per-call token ceiling. Forced-schema tool calls rarely need
# more than a few KB; bump per call if synthesizing a 10-section report.
DEFAULT_MAX_TOKENS = 4096

# The single tool the model is forced to call. Arbitrary name — never
# exposed to the user — but stable for cache-prefix safety.
SUBMIT_TOOL_NAME = "submit_response"
SUBMIT_TOOL_DESCRIPTION = (
    "Submit your response. The input must conform exactly to the "
    "schema; do not include free-form text or commentary."
)


T = TypeVar("T", bound=BaseModel)


def resolve_model(tier: Tier) -> str:
    """The model a ``tier`` call will use under the current settings."""
    override = settings.LLM_TRIAGE_MODEL if tier == "triage" else settings.LLM_SYNTH_MODEL
    return override or DEFAULT_MODELS[settings.LLM_PROVIDER][tier]


def provider_api_key_configured() -> bool:
    """True when the active provider's API key is set. Gates the live evals."""
    if settings.LLM_PROVIDER == "deepseek":
        return bool(settings.DEEPSEEK_API_KEY)
    return bool(settings.ANTHROPIC_API_KEY)


# ── Anthropic adapter ─────────────────────────────────────────────────

# Lazy-initialized so the module can be imported without an API key
# present (tests, the eval-rubric unit tests, etc.). The first real call
# triggers construction; an empty key raises a clear error instead of a
# generic 401 from the API.
_anthropic_client: AsyncAnthropic | None = None


def _get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. "
                "Run `cp .env.example .env` and fill it in for local dev, "
                "or `fly secrets set ANTHROPIC_API_KEY=...` for production.",
            )
        _anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


def _anthropic_tool(schema: type[BaseModel]) -> dict:
    """Wrap a Pydantic schema as the single forced tool definition."""
    return {
        "name": SUBMIT_TOOL_NAME,
        "description": SUBMIT_TOOL_DESCRIPTION,
        "input_schema": schema.model_json_schema(),
    }


def _anthropic_system(system: str | None) -> list[dict] | NotGiven:
    """
    System prompt with prompt caching enabled on the last (only) block.

    We pass system as a list-of-blocks even when there's just one block,
    because that's the form that accepts ``cache_control``. Identical
    system text across calls hits the prefix cache. If hits stop
    accumulating, the most common cause is a timestamp in the prompt.
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


async def _anthropic_structured_call(
    *,
    model: str,
    schema: type[T],
    prompt: str,
    system: str | None,
    max_tokens: int,
    service_id: str,
) -> T:
    client = _get_anthropic_client()

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
        try:
            msg = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=_anthropic_system(system),
                messages=[{"role": "user", "content": prompt}],
                tools=[_anthropic_tool(schema)],
                tool_choice={"type": "tool", "name": SUBMIT_TOOL_NAME},
            )
        except anthropic.APIStatusError as exc:
            raise RuntimeError(
                f"Anthropic API returned HTTP {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIError as exc:
            raise RuntimeError(f"Anthropic API call failed: {exc}") from exc

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


# ── Dispatch ──────────────────────────────────────────────────────────


async def _structured_call(
    tier: Tier,
    *,
    schema: type[T],
    prompt: str,
    system: str | None,
    max_tokens: int,
) -> T:
    provider = settings.LLM_PROVIDER
    model = resolve_model(tier)
    service_id = f"{provider}.{tier}"
    if provider == "deepseek":
        return await llm_deepseek.structured_call(
            model=model,
            schema=schema,
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            service_id=service_id,
            tool_name=SUBMIT_TOOL_NAME,
            tool_description=SUBMIT_TOOL_DESCRIPTION,
        )
    return await _anthropic_structured_call(
        model=model,
        schema=schema,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        service_id=service_id,
    )


async def triage_call(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> T:
    """
    Cheap-tier call for classification / planning. Use for any structured
    decision where small-model capability is sufficient (classify a
    headline or risk paragraph, extract a known-shape entity).
    """
    return await _structured_call(
        "triage", schema=schema, prompt=prompt, system=system, max_tokens=max_tokens
    )


async def synth_call(
    prompt: str,
    schema: type[T],
    *,
    system: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> T:
    """
    Capable-tier call for synthesis. Use for the final write-up where
    quality matters (the research report itself, multi-source
    reconciliation, nuanced summary).
    """
    return await _structured_call(
        "synth", schema=schema, prompt=prompt, system=system, max_tokens=max_tokens
    )
