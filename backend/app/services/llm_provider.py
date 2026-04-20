"""Central LLM provider abstraction.

Supports three OpenAI-compatible backends, switched via the
``LLM_PROVIDER`` env var:

* ``openai``               – native OpenAI (default).
* ``b-api-openai``         – B-API proxy that forwards to OpenAI.
* ``b-api-academiccloud``  – B-API proxy that forwards to AcademicCloud
  (open-source models hosted at GWDG).

All three speak the OpenAI Chat-Completions / Embeddings wire format,
so we can keep using the official ``openai`` Python SDK and just swap
the ``base_url`` and the auth header.

Env vars
--------
LLM_PROVIDER       openai | b-api-openai | b-api-academiccloud   (default: openai)
OPENAI_API_KEY     required for provider=openai
B_API_KEY          required for provider=b-api-*
B_API_BASE_URL     default: https://b-api.staging.openeduhub.net/api/v1/llm
LLM_CHAT_MODEL     override chat model
LLM_EMBED_MODEL    override embedding model

GPT-5-series parameters (only active for native OpenAI + GPT-5 models)
---------------------------------------------------------------------
LLM_VERBOSITY        low | medium | high                (default: medium)
LLM_REASONING_EFFORT none | low | medium | high | xhigh (default: low)

Key behaviour on /v1/chat/completions (the endpoint we use):

* ``verbosity`` is always sent for GPT-5 models — it works with or without
  function tools and drives answer length.
* ``reasoning_effort`` is **dropped when tools are attached** because OpenAI
  currently rejects that combination on Chat Completions and points callers
  at the Responses API. For tool-less calls it is sent as configured.
* ``temperature`` / ``top_p`` are only permitted when the effective effort
  is ``none`` (per the GPT-5.4 parameter-compatibility rules). We therefore
  send ``temperature`` only when we are skipping ``reasoning_effort``
  (tools attached → server default of ``none``). On reasoning-enabled calls
  it is dropped silently.
* No ``max_completion_tokens``/``max_output_tokens`` is sent — on reasoning
  models that field is the **total** budget (reasoning + output), which
  would silently starve short call-sites like quick-replies. Output length
  is steered entirely through ``verbosity``.

These parameters are only sent when BOTH conditions hold:
  1) the active provider is native ``openai`` (not any ``b-api-*`` proxy –
     the B-API does not yet forward the new parameters), and
  2) the target model is part of the GPT-5 family (name starts with
     ``gpt-5`` or ``o1``/``o3``/``o4`` reasoning-model names).
For any other model/provider combination the kwargs fall back to the
classic Chat-Completions set (``max_tokens``, ``temperature``, …).

Defaults per provider
---------------------
openai
    chat   = gpt-5.4-mini
    embed  = text-embedding-3-small
b-api-openai
    chat   = gpt-4.1-mini
    embed  = text-embedding-3-small
b-api-academiccloud
    chat   = Qwen/Qwen3.5-122B-A10B-GPTQ-Int4
    embed  = e5-mistral-7b-instruct
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI


_DEFAULT_B_API_BASE = "https://b-api.staging.openeduhub.net/api/v1/llm"

_PROVIDER_DEFAULTS = {
    "openai": {
        # GPT-5.4-mini is the new default for native OpenAI. It understands
        # ``reasoning_effort`` + ``verbosity`` and uses ``max_output_tokens``
        # instead of the deprecated ``max_tokens``.
        "chat": "gpt-5.4-mini",
        "embed": "text-embedding-3-small",
    },
    "b-api-openai": {
        # B-API proxy does not yet forward GPT-5-only parameters → keep the
        # classic GPT-4.1-mini default there.
        "chat": "gpt-4.1-mini",
        "embed": "text-embedding-3-small",
    },
    "b-api-academiccloud": {
        "chat": "Qwen/Qwen3.5-122B-A10B-GPTQ-Int4",
        "embed": "e5-mistral-7b-instruct",
    },
}


_VERBOSITY_CHOICES = {"low", "medium", "high"}
# GPT-5.4 supports: none (default), low, medium, high, xhigh.
# "minimal" is GPT-5 (pre-5.2) only and is accepted as an alias for "none" here.
_EFFORT_CHOICES = {"none", "minimal", "low", "medium", "high", "xhigh"}


def get_provider() -> str:
    p = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    if p not in _PROVIDER_DEFAULTS:
        p = "openai"
    return p


def get_chat_model() -> str:
    override = (os.getenv("LLM_CHAT_MODEL") or "").strip()
    if override:
        return override
    # Backwards compat: legacy OPENAI_MODEL still wins for the openai provider
    legacy = (os.getenv("OPENAI_MODEL") or "").strip()
    if legacy and get_provider() == "openai":
        return legacy
    return _PROVIDER_DEFAULTS[get_provider()]["chat"]


def get_embed_model() -> str:
    override = (os.getenv("LLM_EMBED_MODEL") or "").strip()
    if override:
        return override
    return _PROVIDER_DEFAULTS[get_provider()]["embed"]


def is_openai_native() -> bool:
    """True only for the native OpenAI provider.

    Used to gate features that exist *only* on api.openai.com (e.g. the
    free moderations endpoint, Whisper speech, TTS).
    """
    return get_provider() == "openai"


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    """Build a single shared AsyncOpenAI client for the active provider."""
    provider = get_provider()
    base = (os.getenv("B_API_BASE_URL") or _DEFAULT_B_API_BASE).rstrip("/")
    b_key = (os.getenv("B_API_KEY") or "").strip()

    if provider == "b-api-openai":
        return AsyncOpenAI(
            api_key=b_key or "unused",
            base_url=f"{base}/openai",
            default_headers={"X-API-KEY": b_key} if b_key else None,
        )
    if provider == "b-api-academiccloud":
        return AsyncOpenAI(
            api_key=b_key or "unused",
            base_url=f"{base}/academiccloud",
            default_headers={"X-API-KEY": b_key} if b_key else None,
        )
    # native openai
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def reset_client_cache() -> None:
    """Drop the cached client (used by tests / hot-reload)."""
    get_client.cache_clear()


# ── GPT-5 parameter handling ───────────────────────────────────────

def is_gpt5_model(model: str | None = None) -> bool:
    """True if the model name belongs to OpenAI's reasoning-capable GPT-5 family.

    Also covers the o1/o3/o4 reasoning models which share the same
    ``reasoning_effort``/``max_output_tokens`` contract.
    """
    name = (model or get_chat_model() or "").strip().lower()
    if not name:
        return False
    return (
        name.startswith("gpt-5")
        or name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
    )


def supports_gpt5_params(model: str | None = None) -> bool:
    """The new parameters only travel over the native OpenAI endpoint.

    The B-API proxy (``b-api-openai`` / ``b-api-academiccloud``) does not yet
    forward ``verbosity`` or ``reasoning_effort`` — sending them there either
    fails the request or is silently ignored. We gate the parameters behind
    both the model family and the provider.
    """
    return is_openai_native() and is_gpt5_model(model)


def get_verbosity() -> str:
    """Default answer-length control for GPT-5 models (``medium`` by default).

    ``medium`` matches the GPT-5.4 model default and produces answer lengths
    close to what gpt-4.1-mini used to emit. Use ``low`` for terse outputs,
    ``high`` for long-form explanations.
    """
    v = (os.getenv("LLM_VERBOSITY") or "medium").strip().lower()
    return v if v in _VERBOSITY_CHOICES else "medium"


def get_reasoning_effort() -> str:
    """Default reasoning depth for GPT-5 models (``low`` by default).

    ``none`` = no thinking (fastest), ``low`` = quick step-through,
    ``medium``/``high`` = deeper multi-step reasoning, ``xhigh`` = maximal.
    """
    e = (os.getenv("LLM_REASONING_EFFORT") or "low").strip().lower()
    return e if e in _EFFORT_CHOICES else "low"


def build_chat_kwargs(
    *,
    model: str | None = None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    verbosity: str | None = None,
    reasoning_effort: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Assemble kwargs for ``client.chat.completions.create`` based on model.

    Callers pass the "classic" parameter set (``max_tokens``, ``temperature``).
    When the target model supports the new GPT-5 contract AND we're on the
    native OpenAI endpoint, this helper rewrites the kwargs according to the
    GPT-5.4 parameter-compatibility rules:

    * ``verbosity`` — always sent (default ``medium``). Drives answer length
      and is compatible with both tool and tool-less turns.
    * ``reasoning_effort`` — sent on tool-less turns (default ``low``).
      Dropped when tools are attached, because OpenAI currently rejects
      ``tools + reasoning_effort`` on /v1/chat/completions and routes callers
      to /v1/responses instead. With effort dropped the server falls back to
      ``none``.
    * ``temperature`` / ``top_p`` — only allowed when the effective
      reasoning effort is ``none``. That means they ride along on
      tool-carrying calls (no effort sent → server default ``none``) but are
      silently dropped on reasoning-enabled calls.
    * ``max_completion_tokens`` is deliberately **not** set. On reasoning
      models it is the *total* budget (reasoning + output), so a small value
      like 150 (quick-replies) or 2000 (learning-path) gets eaten up by the
      reasoning pass and produces an empty answer. Output length is steered
      through ``verbosity`` instead. Callers who pass ``max_tokens`` on
      classic models still get it forwarded; GPT-5 just ignores it.

    Anything else is passed through unchanged, so the older gpt-4.1-mini
    branch and the B-API proxies keep their existing wire format.
    """
    resolved_model = (model or get_chat_model())
    kwargs: dict[str, Any] = {"model": resolved_model, "messages": messages}

    if tools:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if response_format is not None:
        kwargs["response_format"] = response_format

    use_gpt5 = supports_gpt5_params(resolved_model)
    if use_gpt5:
        has_tools = bool(tools)
        # Always safe: verbosity is accepted with or without tools.
        kwargs["verbosity"] = verbosity or get_verbosity()

        # reasoning_effort: only send on tool-less calls. With tools attached
        # the server defaults to ``none``, which is what we want anyway
        # because it also lets temperature/top_p ride along.
        effective_effort_is_none = True
        if not has_tools:
            effort = reasoning_effort or get_reasoning_effort()
            if effort != "none":
                kwargs["reasoning_effort"] = effort
                effective_effort_is_none = False

        # temperature/top_p are only permitted at effort=none.
        if effective_effort_is_none:
            if temperature is not None:
                kwargs["temperature"] = temperature
            # top_p not plumbed through today; add here if a caller needs it.
        # Output-token budget is NOT set on GPT-5 — see docstring for why.
    else:
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

    # Forward any caller-provided extras (e.g. `stop`, `n`, `top_p`).
    for k, v in extra.items():
        if v is not None:
            kwargs[k] = v
    return kwargs
