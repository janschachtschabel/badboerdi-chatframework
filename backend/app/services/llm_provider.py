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
B_API_BASE_URL     default: https://b-api.prod.openeduhub.net/api/v1/llm
                   (staging fallback: https://b-api.staging.openeduhub.net/api/v1/llm)
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

import inspect
import logging
import os
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI
from openai.resources.chat.completions import AsyncCompletions

logger = logging.getLogger(__name__)


# Production B-API of the OpenEduHub network. Override with B_API_BASE_URL
# to point at the staging instance during integration testing:
#   B_API_BASE_URL=https://b-api.staging.openeduhub.net/api/v1/llm
_DEFAULT_B_API_BASE = "https://b-api.prod.openeduhub.net/api/v1/llm"


# ── SDK-capability introspection (runs once at import time) ──────────
#
# Older openai-SDKs (<1.65) don't accept ``verbosity``/``reasoning_effort``
# as kwargs to ``chat.completions.create``. If the running SDK predates
# those parameters, dropping them here keeps the request working — the
# server-side default ("medium" verbosity, "none" reasoning) is identical
# to what we'd send anyway, so quality is unaffected.
#
# We rely on the named-parameter signature; if the SDK uses ``**kwargs``
# only, we conservatively assume support (passing unknown kwargs to a
# **kwargs-method makes them visible as JSON-body fields, which is what
# we want).

_SDK_PARAMS: set[str]
try:
    _SDK_PARAMS = set(inspect.signature(AsyncCompletions.create).parameters)
except (TypeError, ValueError):  # pragma: no cover — defensive
    _SDK_PARAMS = set()


def _sdk_supports(kwarg: str) -> bool:
    """Whether the installed openai SDK accepts ``kwarg`` on ``create()``.

    Returns True for unknown signatures (best-effort) — the server will
    then either accept the kwarg or 400 with a clearer error than the
    Python-level ``TypeError``.
    """
    if not _SDK_PARAMS:
        return True
    return kwarg in _SDK_PARAMS or "kwargs" in _SDK_PARAMS


_GPT5_KWARGS_SUPPORTED = _sdk_supports("verbosity")
if not _GPT5_KWARGS_SUPPORTED:
    logger.warning(
        "openai SDK is too old for GPT-5 ``verbosity`` kwarg — those "
        "parameters will be dropped. Upgrade with `pip install -U "
        "'openai>=1.78,<2.0'` for full GPT-5.4-mini support.",
    )

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
        # Default Qwen 3.5 model on the OEH B-API → AcademicCloud
        # endpoint. Name as published by the upstream model registry
        # (lowercase, no quantisation suffix). Probed 2026-04-27.
        "chat": "qwen3.5-122b-a10b",
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


# ── Embedding dimension lookup ───────────────────────────────────
#
# sqlite-vec needs the column dimension fixed at table-creation time
# AND at every INSERT. If a user swaps the embedding model (e.g. from
# text-embedding-3-small → text-embedding-3-large), the dimension
# changes from 1536 → 3072 — storing a 3072-float blob against a
# 1536-float vec column silently drops the row. The mapping below
# turns the model name into its true dimension so `EMBED_DIM` can
# be derived dynamically at import time.
#
# Defaults intentionally leave the current 1536 value for
# text-embedding-3-small unchanged — this is purely additive.

_EMBED_MODEL_DIMS: dict[str, int] = {
    # OpenAI
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    # AcademicCloud / other B-API upstream models
    "e5-mistral-7b-instruct": 4096,
    "bge-m3": 1024,
    "bge-large-en-v1.5": 1024,
    "jina-embeddings-v2-base-de": 768,
    "jina-embeddings-v2-base-en": 768,
}

_EMBED_DIM_DEFAULT = 1536  # safe fallback (OpenAI 3-small / ada-002)


def get_embed_dim(model: str | None = None) -> int:
    """Return the vector dimension of an embedding model.

    Lookup order:
      1. Explicit ``EMBED_DIM`` env var (escape hatch for custom models)
      2. Model-name → dim table above
      3. Default 1536 (safe for OpenAI text-embedding-3-small)

    The resolution is case-insensitive and accepts bare model names
    (``text-embedding-3-large``) or namespaced ones
    (``openai/text-embedding-3-large``).
    """
    env_override = (os.getenv("EMBED_DIM") or "").strip()
    if env_override.isdigit():
        return int(env_override)
    name = (model or get_embed_model() or "").lower().strip()
    # Strip provider prefix so "openai/text-embedding-3-small" resolves too
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return _EMBED_MODEL_DIMS.get(name, _EMBED_DIM_DEFAULT)


def is_openai_native() -> bool:
    """True only for the native OpenAI provider.

    Used to gate features that exist *only* on api.openai.com AND
    require the chat client to be on the same connection (e.g. the
    GPT-5 ``verbosity`` / ``reasoning_effort`` parameters which are
    not forwarded by the B-API proxy).

    For moderation / Whisper / TTS prefer the side-channel helpers
    (``get_moderation_client()``) — those work on B-API setups too,
    as long as ``OPENAI_API_KEY`` is provided alongside.
    """
    return get_provider() == "openai"


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    """Build a single shared AsyncOpenAI client for the active provider.

    Native-OpenAI base URL can be overridden via ``OPENAI_BASE_URL`` to point
    at any OpenAI-compatible endpoint (Azure OpenAI, LiteLLM, LocalAI,
    Ollama's OpenAI shim, …). If unset, the SDK default (https://api.openai.com/v1)
    applies, preserving existing behaviour.
    """
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
    # native openai (or any OpenAI-compatible endpoint via OPENAI_BASE_URL)
    #
    # Subtlety: the OpenAI SDK reads ``OPENAI_BASE_URL`` from the environment
    # itself when ``base_url=None`` is passed. If that env var is set to an
    # empty string (common in Docker setups using ``${VAR:-}`` substitution),
    # the SDK adopts the empty string as the base URL → httpx then fails with
    # ``UnsupportedProtocol``. Always pass an explicit fallback so the empty
    # env value can never reach the SDK's auto-resolution.
    openai_base = (
        (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
        or "https://api.openai.com/v1"
    )
    return AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=openai_base,
    )


def reset_client_cache() -> None:
    """Drop the cached clients (used by tests / hot-reload)."""
    get_client.cache_clear()
    get_moderation_client.cache_clear()
    get_embedding_client.cache_clear()


# ── Native-OpenAI side-channel for moderation / speech ────────────────
#
# Some endpoints exist *only* on api.openai.com:
#   - /v1/moderations  (free safety classifier)
#   - /v1/audio/transcriptions  (Whisper / gpt-4o-transcribe — STT)
#   - /v1/audio/speech  (TTS)
#
# The B-API proxies don't forward these. Historically we silently skipped
# moderation / speech on b-api setups. Better: build a *separate* native
# OpenAI client when ``OPENAI_API_KEY`` is set, even if the chat traffic
# goes through B-API. This way operators can keep their B-API contract
# for chat/embeddings *and* still get moderation as a safety floor by
# providing an OpenAI key alongside.

@lru_cache(maxsize=1)
def get_moderation_client() -> AsyncOpenAI | None:
    """Native-OpenAI client for the free /v1/moderations endpoint.

    Returns:
      - on ``LLM_PROVIDER=openai``: same instance as ``get_client()``
        (avoids two separate connection pools when the chat client
        already points at api.openai.com).
      - on ``LLM_PROVIDER=b-api-*`` *and* ``OPENAI_API_KEY`` set:
        a fresh native-OpenAI client using OPENAI_API_KEY +
        OPENAI_BASE_URL (or SDK default). Lets B-API operators still
        run the safety floor.
      - ``None`` when no usable OpenAI key is available — callers
        should treat that as "skip moderation" (the regex-based
        safety floor remains).
    """
    # Native: just reuse the chat client, same provider, same pool.
    if get_provider() == "openai":
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        return get_client() if api_key else None

    # B-API path: only build a moderation client if the operator has
    # explicitly opted in by providing an OpenAI key.
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    # Empty OPENAI_BASE_URL must not reach the SDK — see comment in
    # get_client() above.
    base = (
        (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
        or "https://api.openai.com/v1"
    )
    return AsyncOpenAI(api_key=api_key, base_url=base)


def has_moderation() -> bool:
    """True iff a usable OpenAI moderation client can be built."""
    return get_moderation_client() is not None


# ── Embedding-Client side-channel ────────────────────────────────────
#
# B-API → AcademicCloud hosts only chat-ai LLMs — no OpenAI-style
# embedding models. With LLM_PROVIDER=b-api-academiccloud, the existing
# 1536-dim RAG corpus (built with text-embedding-3-small) would break
# because we'd try to query academiccloud for an OpenAI embed model.
#
# Solution: same pattern as moderation. When provider=b-api-academiccloud
# and OPENAI_API_KEY is configured, route embeddings through native
# OpenAI directly. Chat keeps flowing through B-API.

@lru_cache(maxsize=1)
def get_embedding_client() -> AsyncOpenAI:
    """Client for ``/v1/embeddings`` calls.

    Returns:
      - on ``LLM_PROVIDER=openai`` / ``b-api-openai``: the main chat
        client (same pool, since both endpoints forward
        ``text-embedding-3-small``).
      - on ``LLM_PROVIDER=b-api-academiccloud`` + ``OPENAI_API_KEY``
        set: a separate native-OpenAI client so embeddings keep working
        with the existing 1536-dim RAG database.
      - on ``LLM_PROVIDER=b-api-academiccloud`` without ``OPENAI_API_KEY``:
        falls back to the main client. The caller must then have set
        ``LLM_EMBED_MODEL`` to an academiccloud-supported model
        (e.g. ``e5-mistral-7b-instruct``) — and the RAG database needs
        to be re-indexed at that model's dimension.
    """
    provider = get_provider()
    if provider in ("openai", "b-api-openai"):
        return get_client()
    # b-api-academiccloud: prefer native OpenAI side-channel
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if api_key:
        base = (
            (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
            or "https://api.openai.com/v1"
        )
        return AsyncOpenAI(api_key=api_key, base_url=base)
    return get_client()


def get_embedding_model_for_client() -> str:
    """Embed-model resolved against the client returned by
    ``get_embedding_client()``.

    On academiccloud setups with an OpenAI side-channel, prefer a real
    OpenAI embed model (text-embedding-3-small) so the 1536-dim DB keeps
    working — even when ``LLM_EMBED_MODEL`` points at academiccloud's
    default ``e5-mistral-7b-instruct``.
    """
    override = (os.getenv("LLM_EMBED_MODEL") or "").strip()
    if override:
        return override
    if get_provider() == "b-api-academiccloud" and os.getenv("OPENAI_API_KEY"):
        return "text-embedding-3-small"
    return _PROVIDER_DEFAULTS[get_provider()]["embed"]


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


# ── Per-model token-budget profiles (B-API + AcademicCloud) ──────────
#
# Some models served via the B-API silently spend a large chunk of their
# completion-token budget on internal reasoning *before* producing any
# user-visible content. Without compensation a caller that asks for e.g.
# ``max_tokens=300`` (typical quick-reply scenario) gets ZERO output
# because the entire budget was consumed by hidden reasoning steps.
#
# Empirical findings (probed 2026-04-27 against b-api.prod.openeduhub.net,
# trivial prompt "Was ist 2+2?"):
#
#   qwen3.5-397b-a17b      ~ 400-1000 silent reasoning tokens
#   qwen3.5-122b-a10b      ~ 600 silent reasoning tokens
#   qwen3.5-35b-a3b        ~ 400-500 silent reasoning tokens
#   qwen3.5-27b            ~ 300-500 silent reasoning tokens
#   openai-gpt-oss-120b    ~ 50-200 reasoning tokens, EXPOSED via
#                            response.choices[0].message.reasoning_content
#   glm-4.7                direct, no reasoning overhead
#   mistral-large-3        direct, no reasoning overhead
#   gpt-4.1-mini / GPT-4o  direct
#   gpt-5*                 reasoning_effort/verbosity controlled (separate path)
#
# The B-API silently ignores ``chat_template_kwargs`` /
# ``enable_thinking=false`` / ``reasoning=False``-type opt-outs — so the
# only working strategy is to add a buffer on top of the caller's
# requested output budget.

_MODEL_PROFILES: list[tuple[str, dict[str, int]]] = [
    # Qwen 3.5 reasoning family — silent reasoning, varying budget.
    # Substring match (lower-case) so canonical and namespaced spellings
    # (``qwen3.5-397b-a17b`` vs ``Qwen/Qwen3.5-397B-A17B``) both trigger.
    ("qwen3.5-397b-a17b", {"silent_reasoning_buffer": 1100, "min_max_tokens": 1500}),
    # Probed 2026-04-27: Qwen 122b spent up to 1200 silent-reasoning
    # tokens for short prompts (Schüler intents). Floor 1500 ensures
    # the model has room to *also* produce visible output.
    ("qwen3.5-122b-a10b", {"silent_reasoning_buffer": 900,  "min_max_tokens": 1500}),
    ("qwen3.5-35b-a3b",   {"silent_reasoning_buffer": 600,  "min_max_tokens": 1000}),
    ("qwen3.5-27b",       {"silent_reasoning_buffer": 500,  "min_max_tokens": 1000}),
    # gpt-oss-120b — visible reasoning_content; the buffer covers the
    # reasoning tokens which are already counted in completion_tokens.
    ("gpt-oss-120b",      {"visible_reasoning_buffer": 200, "min_max_tokens": 1200}),
    # Direct (non-reasoning) classic models — small floors so callers
    # that pass tiny ``max_tokens`` (e.g. quick replies at 150) still
    # leave room for one usable sentence.
    ("mistral-large-3",   {"min_max_tokens": 1000}),
    ("glm-4.7",           {"min_max_tokens": 800}),
]


def model_profile(model: str | None = None) -> dict[str, int]:
    """Return the per-model token-budget profile for ``model``.

    Substring-match against the lowercased model name. Returns an empty
    dict for models without a known profile — in that case the caller's
    parameters are forwarded unchanged.
    """
    name = (model or get_chat_model() or "").lower()
    for key, profile in _MODEL_PROFILES:
        if key in name:
            return profile
    return {}


def silently_reasons(model: str | None = None) -> bool:
    """True when the model spends completion tokens on hidden reasoning."""
    return "silent_reasoning_buffer" in model_profile(model)


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
        # Verbosity drives answer length on GPT-5 models. Skip sending it
        # if the installed SDK is too old to accept the kwarg — server
        # default (medium) is identical to ours, so quality is unchanged.
        if _GPT5_KWARGS_SUPPORTED:
            kwargs["verbosity"] = verbosity or get_verbosity()

        # reasoning_effort: only send on tool-less calls. With tools attached
        # the server defaults to ``none``, which is what we want anyway
        # because it also lets temperature/top_p ride along.
        effective_effort_is_none = True
        if not has_tools and _GPT5_KWARGS_SUPPORTED:
            effort = reasoning_effort or get_reasoning_effort()
            if effort != "none":
                kwargs["reasoning_effort"] = effort
                effective_effort_is_none = False

        # temperature/top_p are only permitted at effort=none.
        # ALSO: certain reasoning-only models (gpt-5-mini, gpt-5, o1/o3/o4)
        # reject custom temperature even at effort=none — they only accept
        # the default of 1. gpt-5.4-mini DOES accept custom temperature.
        # Detect by name: only families known to accept temperature get it.
        _name_lower = resolved_model.lower()
        _accepts_temperature = (
            _name_lower.startswith("gpt-5.4")  # gpt-5.4-mini etc.
        )
        if effective_effort_is_none and _accepts_temperature:
            if temperature is not None:
                kwargs["temperature"] = temperature
            # top_p not plumbed through today; add here if a caller needs it.
        # Output-token budget is NOT set on GPT-5 — see docstring for why.
    else:
        if temperature is not None:
            kwargs["temperature"] = temperature
        # Per-model max_tokens shaping: bump the budget for known
        # reasoning models so the caller's intended output size actually
        # reaches the user even when 600+ tokens silently disappear into
        # hidden reasoning. See _MODEL_PROFILES for the table.
        if max_tokens is not None:
            shaped = _shape_max_tokens(resolved_model, max_tokens)
            kwargs["max_tokens"] = shaped
        else:
            # Caller passed no explicit cap. For reasoning models a
            # missing cap means "server default" (often quite low) so we
            # set the model's profile floor — otherwise reasoning eats
            # the whole budget.
            floor = model_profile(resolved_model).get("min_max_tokens", 0)
            if floor:
                kwargs["max_tokens"] = floor

    # Forward any caller-provided extras (e.g. `stop`, `n`, `top_p`).
    for k, v in extra.items():
        if v is not None:
            kwargs[k] = v
    return kwargs


def _shape_max_tokens(model: str, requested: int) -> int:
    """Apply per-model token-budget profile to a caller-requested value.

    Adds the silent-/visible-reasoning buffer on top, then clamps to the
    model's known minimum-useful budget. Models without a profile pass
    through unchanged.
    """
    p = model_profile(model)
    if not p:
        return requested
    buf = p.get("silent_reasoning_buffer", 0) + p.get("visible_reasoning_buffer", 0)
    shaped = requested + buf
    floor = p.get("min_max_tokens", 0)
    if floor and shaped < floor:
        shaped = floor
    return shaped
