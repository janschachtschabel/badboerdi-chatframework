"""RAG service: ingest documents via markitdown, chunk, embed, and search."""

from __future__ import annotations

import os
import re
import struct
from typing import Any

import httpx

from app.services.database import store_rag_chunk, get_rag_chunks, search_rag_chunks
from app.services.llm_provider import (
    get_client,
    get_embedding_client,
    get_embedding_model_for_client,
)

# Chat client (kept for legacy reference). Embeddings now go through
# get_embedding_client(): native OpenAI side-channel when on
# b-api-academiccloud + OPENAI_API_KEY, main client otherwise.
client = get_client()
embed_client = get_embedding_client()
EMBED_MODEL = get_embedding_model_for_client()


async def get_embedding(text: str) -> list[float]:
    """Get embedding vector from the configured embedding endpoint."""
    resp = await embed_client.embeddings.create(model=EMBED_MODEL, input=text[:8000])
    return resp.data[0].embedding


def embedding_to_bytes(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def chunk_markdown(text: str, max_chunk: int = 1000, overlap: int = 150) -> list[str]:
    """Split text into chunks using a multi-strategy approach.

    Strategy priority:
    1. Split at markdown headings (H1-H3)
    2. If that produces too few chunks, split at paragraph boundaries (double newline)
    3. Final fallback: split at sentence boundaries with overlap
    """
    # ── Strategy 1: heading-based split ─────────────────────
    sections = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
    heading_sections = [s.strip() for s in sections if s.strip()]

    # If headings produce good granularity, use them
    if len(heading_sections) > 1:
        return _merge_sections(heading_sections, max_chunk)

    # ── Strategy 2: paragraph-based split ───────────────────
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if len(paragraphs) > 1:
        return _merge_sections(paragraphs, max_chunk)

    # ── Strategy 3: sentence-based split with overlap ───────
    # For texts without headings or paragraph breaks (e.g. raw PDF text)
    return _split_by_sentences(text, max_chunk, overlap)


def _merge_sections(sections: list[str], max_chunk: int) -> list[str]:
    """Merge small sections into chunks up to max_chunk size."""
    chunks: list[str] = []
    current = ""

    for section in sections:
        if not section:
            continue
        if len(current) + len(section) + 2 > max_chunk and current:
            chunks.append(current.strip())
            current = section
        else:
            current = (current + "\n\n" + section) if current else section

    if current.strip():
        chunks.append(current.strip())

    # Post-process: split any oversized chunks
    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chunk:
            final.append(chunk)
        else:
            final.extend(_split_by_sentences(chunk, max_chunk, 100))

    return final if final else [sections[0][:max_chunk]]


def _split_by_sentences(text: str, max_chunk: int, overlap: int) -> list[str]:
    """Split text at sentence boundaries with overlap for context continuity."""
    # Split on sentence-ending punctuation followed by space or newline
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        # Absolute fallback: hard split at max_chunk
        return [text[i:i + max_chunk] for i in range(0, len(text), max_chunk - overlap)]

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chunk and current:
            chunks.append(current.strip())
            # Overlap: keep last ~overlap chars for context continuity
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:].lstrip() + " " + sentence
            else:
                current = sentence
        else:
            current = (current + " " + sentence) if current else sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_chunk]]


async def convert_to_markdown(file_path: str) -> str:
    """Convert any document to markdown using markitdown."""
    try:
        from markitdown import MarkItDown
        mid = MarkItDown()
        result = mid.convert(file_path)
        return result.text_content
    except Exception as e:
        return f"Fehler beim Konvertieren: {e}"


async def convert_url_to_markdown(url: str) -> str:
    """Fetch a URL and convert to markdown using markitdown."""
    try:
        from markitdown import MarkItDown
        mid = MarkItDown()
        result = mid.convert_url(url)
        return result.text_content
    except Exception as e:
        return f"Fehler beim Konvertieren: {e}"


async def ingest_document(
    area: str,
    title: str,
    source: str,
    markdown_content: str,
) -> int:
    """Chunk, embed, and store a markdown document. Returns chunk count."""
    chunks = chunk_markdown(markdown_content)

    for i, chunk in enumerate(chunks):
        embedding = await get_embedding(chunk)
        emb_bytes = embedding_to_bytes(embedding)
        await store_rag_chunk(area, title, source, i, chunk, emb_bytes)

    return len(chunks)


async def query_rag(query: str, area: str = "general", top_k: int = 3) -> list[dict]:
    """Search RAG knowledge base by semantic similarity."""
    query_emb = await get_embedding(query)
    results = await search_rag_chunks(area, query_emb, top_k)
    return results


# ── Retrieval-Defaults ─────────────────────────────────────────────
#
# Tunable retrieval parameters. Defaults reproduce the previous
# hard-coded behaviour (top_k=15, min_score=0.30 for pre-fetch via
# llm_service; top_k=3, min_score=0.25 for arbitrary get_rag_context
# callers; per-area cap unlimited). Can be overridden via:
#   - ENV vars (highest precedence)
#   - 01-base/rag-retrieval.yaml (optional, editable in Studio)
#
# Never lower this defensively — the numbers below match what shipped.

_RAG_DEFAULTS = {
    "top_k": 15,
    "min_score": 0.30,
    "max_chars_per_area": 3000,  # cap per-area text injected into prompt
}


# ── Cross-Encoder Reranker (ONNX int8, always on) ──────────────────
#
# Second-stage ranker that scores (query, chunk) jointly after the
# embedding retrieval. LLM-as-Judge eval (10 queries) showed 8/10
# wins, 0/10 losses vs. embedding-only ranking — so it's always on.
#
# Backend: pure onnxruntime + HF tokenizer, int8-quantized mMiniLM
# (cross-encoder/mmarco-mMiniLMv2-L12-H384-v1), ~130 MB on disk,
# ~600 ms overhead per query on CPU. No torch at runtime.
#
# Pre-requisite: the exported model must exist under
#   backend/models/cross-encoder__mmarco-mMiniLMv2-L12-H384-v1-int8/
# Regenerate with: python -m scripts.export_reranker_onnx
#
# If the model dir is missing we log a WARNING and silently fall back
# to pure embedding ranking — the chatbot still works.

_RERANK_MODEL_SLUG = "cross-encoder__mmarco-mMiniLMv2-L12-H384-v1-int8"
_RERANK_CANDIDATES = 25   # top-N from embedding retrieval fed into rerank

# Sentinel: None = not yet loaded, False = load failed (don't retry),
# _OnnxReranker instance otherwise.
_reranker: Any = None
_reranker_loaded = False


class _OnnxReranker:
    """Minimal onnxruntime-based cross-encoder. No torch dependency."""

    def __init__(self, model_dir: str):
        import numpy as np  # noqa: F401
        import onnxruntime as ort
        from transformers import AutoTokenizer
        from pathlib import Path

        d = Path(model_dir)
        # Quantized exports can use any of these filenames.
        onnx_candidates = ["model_quantized.onnx", "model_int8.onnx", "model.onnx"]
        onnx_file = next((d / name for name in onnx_candidates if (d / name).exists()), None)
        if onnx_file is None:
            found = list(d.glob("*.onnx"))
            if not found:
                raise FileNotFoundError(f"No .onnx file in {model_dir}")
            onnx_file = found[0]
        self.tokenizer = AutoTokenizer.from_pretrained(str(d))
        # Graph optimization to ALL fuses ops / reorders nodes — critical
        # for CPU perf. Threads left at ORT's default (physical cores).
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(onnx_file),
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {inp.name for inp in self.session.get_inputs()}

    def predict(self, pairs: list[tuple[str, str]]):
        import numpy as np

        if not pairs:
            return []
        queries = [p[0] for p in pairs]
        passages = [p[1] for p in pairs]
        enc = self.tokenizer(
            queries, passages,
            padding=True, truncation=True, max_length=512,
            return_tensors="np",
        )
        feed = {
            "input_ids": enc["input_ids"].astype(np.int64),
            "attention_mask": enc["attention_mask"].astype(np.int64),
        }
        if "token_type_ids" in self._input_names and "token_type_ids" in enc:
            feed["token_type_ids"] = enc["token_type_ids"].astype(np.int64)
        out = self.session.run(None, feed)
        logits = out[0]
        if logits.ndim == 2 and logits.shape[-1] == 1:
            logits = logits.squeeze(-1)
        return logits.tolist()


def _reranker_model_dir() -> str | None:
    """Return the canonical model dir path if it exists, else None."""
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent.parent  # backend/
    candidate = here / "models" / _RERANK_MODEL_SLUG
    if candidate.exists() and any(candidate.glob("*.onnx")):
        return str(candidate)
    return None


def _get_reranker():
    """Load reranker on first use. Returns wrapper or None if unavailable."""
    global _reranker, _reranker_loaded
    if _reranker_loaded:
        return _reranker or None
    _reranker_loaded = True

    import logging as _logging
    log = _logging.getLogger(__name__)
    model_dir = _reranker_model_dir()
    if model_dir is None:
        log.warning(
            "RAG reranker model missing — running with embedding-only ranking.\n"
            "    expected:  backend/models/%s/\n"
            "    to enable: cd backend && \\\n"
            "               pip install -r requirements-setup.txt "
            "--extra-index-url https://download.pytorch.org/whl/cpu && \\\n"
            "               python -m scripts.setup",
            _RERANK_MODEL_SLUG,
        )
        _reranker = False
        return None
    try:
        log.info("Loading ONNX reranker from: %s", model_dir)
        _reranker = _OnnxReranker(model_dir)
        return _reranker
    except Exception as e:
        log.warning("Reranker load failed: %s — running without rerank.", e)
        _reranker = False
        return None


async def warmup_reranker() -> None:
    """Load the reranker + run one prediction so the first real request
    doesn't pay the ~1–1.5 s model-load + first-inference cost. Called
    from the FastAPI lifespan handler as a background task.
    """
    import asyncio as _aio
    import logging as _logging
    import time as _time

    log = _logging.getLogger(__name__)
    loop = _aio.get_event_loop()

    def _work():
        t0 = _time.perf_counter()
        rr = _get_reranker()
        if rr is None:
            return None
        # Small dummy prediction to warm tokenizer + first ORT inference
        rr.predict([("warmup", "warmup passage")])
        return (_time.perf_counter() - t0) * 1000

    try:
        # Run in default executor — the model load + ORT call are blocking.
        dt = await loop.run_in_executor(None, _work)
        if dt is not None:
            log.info("Reranker warmup done in %.0fms", dt)
    except Exception as e:
        log.warning("Reranker warmup skipped: %s", e)


def rerank_results(query: str, results: list[dict], top_n: int) -> list[dict]:
    """Rerank retrieval results with a cross-encoder. Falls back to
    embedding-score sort if the reranker is unavailable.
    """
    if not results or top_n <= 0:
        return results[:top_n] if results else []
    rr = _get_reranker()
    if rr is None:
        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return results[:top_n]
    pairs = [(query, r.get("chunk") or "") for r in results]
    try:
        scores = rr.predict(pairs)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).warning("Reranker predict failed: %s", e)
        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return results[:top_n]
    for r, s in zip(results, scores):
        r["rerank_score"] = float(s)
    results.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
    return results[:top_n]


def _parse_float_env(name: str) -> float | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int_env(name: str) -> int | None:
    raw = (os.getenv(name) or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def get_retrieval_settings() -> dict:
    """Resolve retrieval params from ENV > yaml > defaults.

    Keys: ``top_k`` (int), ``min_score`` (float 0-1),
    ``max_chars_per_area`` (int, 0 = no cap).
    """
    settings = dict(_RAG_DEFAULTS)
    # YAML tier (optional)
    try:
        from app.services.config_loader import _load_yaml  # type: ignore
        cfg = _load_yaml("01-base/rag-retrieval.yaml") or {}
        r = cfg.get("retrieval") if isinstance(cfg, dict) else None
        if isinstance(r, dict):
            if isinstance(r.get("top_k"), int) and r["top_k"] > 0:
                settings["top_k"] = r["top_k"]
            if isinstance(r.get("min_score"), (int, float)) and 0 <= r["min_score"] <= 1:
                settings["min_score"] = float(r["min_score"])
            if isinstance(r.get("max_chars_per_area"), int) and r["max_chars_per_area"] >= 0:
                settings["max_chars_per_area"] = r["max_chars_per_area"]
    except Exception:
        pass
    # ENV tier (wins)
    env_top_k = _parse_int_env("RAG_TOP_K")
    if env_top_k and env_top_k > 0:
        settings["top_k"] = env_top_k
    env_score = _parse_float_env("RAG_MIN_SCORE")
    if env_score is not None and 0 <= env_score <= 1:
        settings["min_score"] = env_score
    env_cap = _parse_int_env("RAG_MAX_CHARS_PER_AREA")
    if env_cap is not None and env_cap >= 0:
        settings["max_chars_per_area"] = env_cap
    return settings


async def get_rag_context(query: str, areas: list[str] | None = None, top_k: int = 3,
                          min_score: float = 0.25,
                          max_chars_per_area: int = 0) -> str:
    """Get RAG context string for injection into LLM prompt.

    Queries all given areas, merges results, filters by relevance threshold,
    and returns the top-k chunks sorted by score. Because all areas share the
    same embedding model and distance metric, scores are directly comparable
    across areas — no per-area guarantees needed.

    Args:
        query: Search query.
        areas: List of knowledge areas to search.
        top_k: Maximum total chunks to return.
        min_score: Minimum similarity score (0-1). Chunks below this threshold
                   are dropped even if top_k is not yet reached. This prevents
                   irrelevant chunks from diluting the context.
        max_chars_per_area: Optional per-area character cap applied AFTER
                            relevance ranking. 0 = unlimited (default).
                            Protects against prompt bloat when many areas
                            each contribute large chunks.
    """
    if not areas:
        areas = ["general"]

    all_results = []
    for area in areas:
        results = await query_rag(query, area, top_k)
        all_results.extend(results)

    if not all_results:
        return ""

    # Sort by embedding score globally across all areas.
    all_results.sort(key=lambda x: x["score"], reverse=True)

    # Embedding score acts as a safety floor — anything below min_score is
    # almost certainly irrelevant, so drop it before (optional) rerank.
    # This also prevents the cross-encoder from wasting cycles on noise.
    plausible = [r for r in all_results if r["score"] >= min_score]

    if not plausible:
        return ""

    # Cross-encoder rerank is always on (ONNX int8). If the model file
    # is missing, rerank_results transparently falls back to score-sort.
    candidates = plausible[:max(_RERANK_CANDIDATES, top_k)]
    top = rerank_results(query, candidates, top_k)

    if not top:
        return ""

    # Optional per-area cap: greedily take highest-scored chunks per area
    # until the char budget is spent. Prevents a single area from monopolising
    # the context window when multiple areas have good matches.
    if max_chars_per_area and max_chars_per_area > 0:
        per_area_used: dict[str, int] = {}
        filtered = []
        for r in top:
            a = r.get("area", "")
            used = per_area_used.get(a, 0)
            chunk = r.get("chunk") or ""
            # Keep the whole chunk if it fits; otherwise truncate the last
            # chunk that crosses the budget and drop subsequent ones for
            # that area.
            if used >= max_chars_per_area:
                continue
            remaining = max_chars_per_area - used
            if len(chunk) > remaining:
                r = dict(r)
                r["chunk"] = chunk[:remaining].rstrip() + "…"
                per_area_used[a] = max_chars_per_area
            else:
                per_area_used[a] = used + len(chunk)
            filtered.append(r)
        top = filtered

    parts = []
    for r in top:
        # Expose rerank score (if present) so prompt/debug shows the effective
        # ordering criterion. Embedding score is kept as "Relevanz".
        tag = f"[Quelle: {r.get('title', r.get('source', 'unbekannt'))} | " \
              f"Bereich: {r['area']} | Relevanz: {r['score']:.2f}"
        if "rerank_score" in r:
            tag += f" | Rerank: {r['rerank_score']:.2f}"
        tag += "]"
        parts.append(f"{tag}\n{r['chunk']}")

    return "\n\n---\n\n".join(parts)


async def get_always_on_rag_context(query: str, top_k: int = 3) -> str:
    """Get RAG context from areas configured as 'always' available.

    These areas are included in every request regardless of pattern config.
    """
    from app.services.config_loader import get_always_on_rag_areas

    always_areas = get_always_on_rag_areas()
    if not always_areas:
        return ""

    return await get_rag_context(query, areas=always_areas, top_k=top_k)
