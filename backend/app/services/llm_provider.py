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

Defaults per provider
---------------------
openai / b-api-openai
    chat   = gpt-4.1-mini
    embed  = text-embedding-3-small
b-api-academiccloud
    chat   = Qwen/Qwen3.5-122B-A10B-GPTQ-Int4
    embed  = e5-mistral-7b-instruct
"""

from __future__ import annotations

import os
from functools import lru_cache

from openai import AsyncOpenAI


_DEFAULT_B_API_BASE = "https://b-api.staging.openeduhub.net/api/v1/llm"

_PROVIDER_DEFAULTS = {
    "openai": {
        "chat": "gpt-4.1-mini",
        "embed": "text-embedding-3-small",
    },
    "b-api-openai": {
        "chat": "gpt-4.1-mini",
        "embed": "text-embedding-3-small",
    },
    "b-api-academiccloud": {
        "chat": "Qwen/Qwen3.5-122B-A10B-GPTQ-Int4",
        "embed": "e5-mistral-7b-instruct",
    },
}


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
